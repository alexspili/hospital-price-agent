"""FastAPI in front of the pipeline: a run per request, its trace streamed as
server-sent events, the built page served from frontend/dist.

This process owns the one DuckDB connection (SPEC "Process model"); worker threads use
`con.cursor()`. A run is a background task in this process, never work done inside a
request: scans take minutes. Two runs at a time is the limit, and the third is told so.
"""

import asyncio
import json
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hpa import catalog, client, demo, llm, pipeline, settings as settings_module, store
from hpa.geo import KM_PER_MILE
from hpa.hospitals import UnknownZip, find_hospitals

MAX_ACTIVE_RUNS = 2
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class RateLimit:
    """Live runs per IP per hour, counted in memory. Restarting the server forgets them,
    which is the right trade for a demo: a sliding window in a dict, not a dependency."""

    def __init__(self, per_hour: int | None, window: float = 3600.0):
        self.per_hour = per_hour
        self.window = window
        self.seen: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def take(self, ip: str, now: float | None = None) -> float | None:
        """None when allowed, otherwise the seconds to wait."""
        if not self.per_hour:
            return None
        now = time.time() if now is None else now
        with self._lock:
            recent = [t for t in self.seen.get(ip, []) if now - t < self.window]
            if len(recent) >= self.per_hour:
                self.seen[ip] = recent
                return round(self.window - (now - recent[0])) or 1
            recent.append(now)
            self.seen[ip] = recent
            return None


@dataclass
class Run:
    """A live run and everything said about it, replayable from any sequence number."""

    id: str
    zip: str
    query: str
    service: dict
    loop: asyncio.AbstractEventLoop
    live: bool = False  # False: answered from what was already scanned, no network
    status: str = "running"  # running | done | failed
    events: list[dict] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, kind: str, **fields) -> None:
        """Called from worker threads: record the event, then hand it to the event loop."""
        with self.lock:
            event = {"seq": len(self.events) + 1, "kind": kind, **fields}
            self.events.append(event)
            queues = list(self.subscribers)
        for q in queues:
            self.loop.call_soon_threadsafe(q.put_nowait, event)

    def state(self) -> dict:
        return {"id": self.id, "zip": self.zip, "query": self.query, "service": self.service,
                "live": self.live, "status": self.status, "events": list(self.events),
                "result": self.result, "error": self.error}


class RunRequest(BaseModel):
    zip: str = Field(min_length=3, max_length=10)
    service: str | None = None
    service_id: str | None = None  # an answer to a clarifying question
    limit: int = Field(default=5, ge=1, le=10)
    live: bool = False  # off by default: answer from what was already scanned
    pin: str | None = None  # the shared PIN, when the deployment asks for one


def create_app(con, db: str | Path = "", settings: settings_module.Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Worker threads hand their events to this loop; grab it while it is running.
        app.state.loop = asyncio.get_running_loop()
        yield
        app.state.pool.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="hospital price agent", docs_url="/api/docs", openapi_url="/api/openapi.json",
                  lifespan=lifespan)
    app.state.con = con
    app.state.db = str(db)
    app.state.settings = settings or settings_module.from_env()
    app.state.limiter = RateLimit(app.state.settings.runs_per_hour)
    app.state.runs = {}
    app.state.pool = ThreadPoolExecutor(max_workers=MAX_ACTIVE_RUNS, thread_name_prefix="run")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "pid": os.getpid(), "db": app.state.db,
                "runs_active": sum(1 for r in app.state.runs.values() if r.status == "running")}

    @app.get("/api/config")
    def config() -> dict:
        """What this deployment allows, so the page can say so before anyone tries."""
        s = app.state.settings
        return {"live_needs_pin": s.live_needs_pin, "max_downloads": s.max_downloads,
                "runs_per_hour": s.runs_per_hour}

    @app.post("/api/runs", status_code=202)
    def start_run(req: RunRequest, request: Request) -> dict:
        """Resolve the service first: a run never starts on a guess (SPEC). When the
        resolver and Claude cannot settle the query, the answer is the question."""
        s = app.state.settings
        if req.live and s.live_needs_pin and not secrets.compare_digest(req.pin or "", s.live_pin):
            raise HTTPException(403, "a live scan needs the PIN; the pre-scanned ZIPs need no PIN")
        if req.live:
            wait = app.state.limiter.take(_client_ip(request, s))
            if wait is not None:
                raise HTTPException(429, f"live runs are limited to {s.runs_per_hour} an hour from one address",
                                    headers={"Retry-After": str(wait)})
        try:
            find_hospitals(app.state.con, req.zip, 1)
        except UnknownZip as e:
            raise HTTPException(400, str(e))
        try:
            # Claude is consulted only on a live run, which has already passed the PIN
            # and the rate limit. A cache-first run costs nothing and must stay that way:
            # otherwise a stranger could spend the daily budget by typing ambiguous
            # service names at a page that asks them for nothing.
            service, r, note = pipeline.resolve_service(req.service or "", service_id=req.service_id,
                                                        con=app.state.con, use_llm=req.live,
                                                        daily_cap_usd=s.daily_cap_usd)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if service is None:
            return {"status": "needs_clarification", "verdict": r.verdict,
                    "question": note or r.reason, "asked_claude": note is not None,
                    "candidates": [pipeline.service_dict(c) for c in r.candidates]}
        active = sum(1 for run in app.state.runs.values() if run.status == "running")
        if active >= MAX_ACTIVE_RUNS:
            raise HTTPException(429, f"busy: {active} runs already in progress, try again in a minute",
                                headers={"Retry-After": "60"})
        run = Run(id=secrets.token_hex(4), zip=req.zip, query=req.service or service.name,
                  service=pipeline.service_dict(service), loop=app.state.loop, live=req.live)
        app.state.runs[run.id] = run
        app.state.pool.submit(_execute, app, run, service, req.limit)
        return {"status": "started", "run_id": run.id, "service": run.service, "live": run.live,
                "resolver": None if r.verdict == catalog.SELECTED else {"verdict": r.verdict, "reason": r.reason},
                "note": note}

    @app.get("/api/runs/{run_id}")
    def run_state(run_id: str) -> dict:
        return _run(app, run_id).state()

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str, request: Request, after: int = 0):
        run = _run(app, run_id)
        last = after
        resumed = request.headers.get("last-event-id")
        if resumed and resumed.isdigit():
            last = max(last, int(resumed))
        queue: asyncio.Queue = asyncio.Queue()
        # Subscribe and snapshot under the same lock, or an event emitted in between
        # would be in neither the backlog nor the queue.
        with run.lock:
            backlog = [e for e in run.events if e["seq"] > last]
            run.subscribers.append(queue)

        async def stream():
            sent = last
            try:
                for event in backlog:
                    sent = event["seq"]
                    yield _sse(event)
                    if event["kind"] == "end":
                        return
                while True:
                    event = await queue.get()
                    if event["seq"] <= sent:
                        continue
                    sent = event["seq"]
                    yield _sse(event)
                    if event["kind"] == "end":
                        return
            finally:
                with run.lock:
                    if queue in run.subscribers:
                        run.subscribers.remove(queue)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/prices")
    def prices(service: str, zip: Annotated[list[str] | None, Query()] = None,
               ccn: str | None = None, limit: int = 5, all: bool = False) -> dict:
        """Prices from what is already stored: the read path `hpa prices` uses while the
        server holds the database.

        Deterministic only: this endpoint is public and unauthenticated, so it never
        spends money. An unclear service name comes back as the resolver's own verdict
        and candidates, which is an answer, not a failure."""
        try:
            return pipeline.prices_payload(app.state.con, service, zip or [], ccn, limit,
                                           shown_lines=None if all else pipeline.SHOWN_LINES,
                                           use_llm=False)
        except UnknownZip as e:
            raise HTTPException(400, str(e))

    @app.get("/api/demo")
    def recorded(zip: str | None = None, service: str | None = None) -> dict:
        """The recorded Houston run, in the same shape as a live one, so the page has one
        way to render and is never empty."""
        if not demo.DEMO_FILE.exists():
            raise HTTPException(404, "no recorded run checked in")
        data = json.loads(demo.DEMO_FILE.read_text())
        if zip is None and service is None:
            return {"recorded_on": data["recorded_on"], "zips": list(data["zips"]),
                    "services": [{"query": q, "name": e["service"], "codes": e["codes"]} for q, e in data["services"].items()]}
        zip = zip or next(iter(data["zips"]))
        service = service or next(iter(data["services"]))
        if zip not in data["zips"] or service not in data["services"]:
            raise HTTPException(404, f"the recorded run has no {service!r} for {zip}")
        return demo_run(data, zip, service)

    if DIST.exists():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
    else:
        @app.get("/", response_class=PlainTextResponse)
        def unbuilt() -> str:
            return "The page is not built yet: cd frontend && npm install && npm run build\nThe API is up: /api/health\n"

    return app


def _run(app: FastAPI, run_id: str) -> Run:
    run = app.state.runs.get(run_id)
    if run is None:
        raise HTTPException(404, f"no run {run_id}")
    return run


def _sse(event: dict) -> str:
    return f"id: {event['seq']}\nevent: {event['kind']}\ndata: {json.dumps(event, default=str)}\n\n"


def _client_ip(request: Request, settings: settings_module.Settings) -> str:
    """Behind Caddy the socket is the proxy, so the real address is the first hop of
    X-Forwarded-For — trusted only when the deployment says it is behind a proxy."""
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded.strip():
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _execute(app: FastAPI, run: Run, service, limit: int) -> None:
    """The run itself, on a worker thread. Failures are reported, never raised into the
    request that started it."""
    s = app.state.settings
    try:
        hospitals = pipeline.run_search(
            app.state.con, run.zip, service, run.emit, query=run.query, limit=limit, live=run.live,
            max_downloads=s.max_downloads, daily_cap_usd=s.daily_cap_usd, keep_downloads=s.keep_downloads,
        )
        run.result = {"zip": run.zip, "service": run.service, "live": run.live, "hospitals": hospitals}
        run.status = "done"
        run.emit("result", **run.result)
    except Exception as e:
        run.status, run.error = "failed", f"{type(e).__name__}: {e}"
        run.emit("error", message=run.error)
    finally:
        run.emit("end")
        # To the process log, not the trace: the operator needs the running total, a
        # visitor does not. Nothing else can read the ledger while this process holds
        # the database (SPEC "Process model").
        if run.live and s.daily_cap_usd:
            print(f"[spend] today ${llm.spend_today(app.state.con):.2f} of ${s.daily_cap_usd:.2f}", flush=True)


def demo_run(data: dict, zip_code: str, query: str) -> dict:
    """Turn the recorded run into the events and result a live run would have produced."""
    hospitals = data["zips"][zip_code]
    entry = data["services"][query]
    recorded = {h["name"]: h for h in entry["hospitals"]}
    events: list[dict] = []

    def add(kind: str, **fields) -> None:
        events.append({"seq": len(events) + 1, "kind": kind, **fields})

    add("trace", text=f"recorded run from {data['recorded_on']} (no network, no database, no API key)")
    add("trace", text=f"nearest {len(hospitals)} hospitals to the centre of {zip_code}")
    for h in hospitals:
        miles = h["distance_km"] / KM_PER_MILE
        add("trace", ccn=h["ccn"], text=f"  {'~' if h['approximate'] else ''}{miles:.1f} mi  {h['name']}")
    add("trace", text=f'"{query}" -> {entry["service"]} ({entry["codes"]})  '
                      f'[mapping {"reviewed" if entry["reviewed"] else "unreviewed"}]')

    rows = []
    for h in hospitals:
        for step in h.get("steps", []):
            add("trace", ccn=h["ccn"], text=f"{h['name']}: {step}")
        rec = recorded.get(h["name"], {})
        # Older recordings carried `lines` as a count; newer ones carry the lines.
        lines = rec.get("lines") if isinstance(rec.get("lines"), list) else []
        count = rec.get("line_count", rec.get("lines") if isinstance(rec.get("lines"), int) else 0)
        row = {"ccn": h["ccn"], "name": h["name"], "distance_km": h["distance_km"],
               "approximate": h["approximate"], "url": rec.get("url") or h.get("mrf_url"),
               "file_date": rec.get("file_date"), "verdict": rec.get("verdict", pipeline.NOT_SCANNED),
               "detail": rec.get("detail") or "", "line_count": count, "headline": rec.get("headline"), "lines": lines}
        rows.append(row)
        add("hospital", hospital=row)

    service = {"id": None, "name": entry["service"], "codes": entry["codes"],
               "reviewed": bool(entry["reviewed"]), "notes": None}
    result = {"zip": zip_code, "service": service, "hospitals": rows}
    add("result", **result)
    add("end")
    return {"status": "recorded", "recorded_on": data["recorded_on"], "zip": zip_code, "query": query,
            "service": service, "events": events, "result": result}


def serve(db, host: str = "127.0.0.1", port: int = 8000, url: str | None = None) -> int:
    """Open the database for writing, announce it, and serve until interrupted."""
    import duckdb
    import uvicorn

    try:
        con = store.connect(db)
    except duckdb.IOException as e:
        print(f"{db} is open in another process; stop it before serving ({e})")
        return 1
    url = url or f"http://{host}:{port}"
    app = create_app(con, db)
    s = app.state.settings
    print(f"live scans: {'PIN required' if s.live_needs_pin else 'open to anyone who can reach this server'}"
          + (f", {s.runs_per_hour}/hour per address" if s.runs_per_hour else "")
          + (f", {s.max_downloads} downloads per run" if s.max_downloads else "")
          + (f", ${s.daily_cap_usd:.2f}/day model budget" if s.daily_cap_usd else ""))
    if not DIST.exists():
        print("note: the page is not built (cd frontend && npm install && npm run build); the API still works")
    with client.marker(url, db):
        uvicorn.run(app, host=host, port=port, log_level="info")
    con.close()
    return 0
