"""One search, end to end: the nearest hospitals, their price files, the rows for a
service, and a verdict for each hospital.

`hpa prices`, `hpa demo --record` and the web server all run this code, so the page and
the terminal cannot drift apart. Everything here is a dict of plain JSON values: the
terminal formats them one way, the page another, and neither computes a price of its own.
"""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from hpa import catalog, compare, discovery, llm, scan, store
from hpa.geo import KM_PER_MILE
from hpa.hospitals import Hospital, find_hospitals

# How many matching lines travel with a result by default; the rest stay a count.
SHOWN_LINES = 8

# Statuses that are not comparability verdicts: they say why there is nothing to compare.
# The verdict vocabulary itself lives in compare.py and is not extended here.
NO_FILE = "no price file located"
NOT_SCANNED = "not scanned"
SCAN_FAILED = "file could not be read"

Emit = Callable[..., None]  # emit(kind, **fields); kinds: trace, progress, hospital

# One scan per URL at a time. Hospitals in a system share a file, and two threads
# extracting the same checksum would delete each other's rows; the second one waits and
# then finds the extraction cached.
_url_locks: dict[str, threading.Lock] = {}
_url_locks_guard = threading.Lock()


def url_lock(url: str) -> threading.Lock:
    with _url_locks_guard:
        return _url_locks.setdefault(url, threading.Lock())


# --- shapes -----------------------------------------------------------------------------

def _money(v) -> float | None:
    """DECIMAL comes back as Decimal; JSON wants a float. Never rounded, never invented."""
    return None if v is None else float(v)


def service_dict(s: catalog.Service) -> dict:
    return {"id": s.id, "name": s.name, "codes": s.code_list, "reviewed": bool(s.reviewed), "notes": s.notes}


def line_dict(l: compare.Line) -> dict:
    return {
        "code_type": l.code_type, "code": l.code, "other_codes": list(l.other_codes),
        "description": l.description, "context": l.context,
        "cash": _money(l.discounted_cash), "gross": _money(l.gross),
        "min": _money(l.minimum), "max": _money(l.maximum),
        "ref": l.source_ref, "note": l.off_template_note,
    }


CHARGE_SQL = """
    SELECT ic.code_type, ic.code,
           (SELECT list(o.code_type || ' ' || o.code ORDER BY o.code_type, o.code) FROM item_codes o
             WHERE o.extraction_id = ic.extraction_id AND o.item_id = ic.item_id AND NOT (o.code_type = ic.code_type AND o.code = ic.code)),
           i.description, ch.setting, ch.billing_class, ch.modifiers,
           ch.gross, ch.discounted_cash, ch.minimum, ch.maximum, ch.source_ref, ch.off_template_note
    FROM charges ch
    JOIN items i ON i.extraction_id = ch.extraction_id AND i.item_id = ch.item_id
    JOIN item_codes ic ON ic.extraction_id = ch.extraction_id AND ic.item_id = ch.item_id
    WHERE ch.extraction_id = ? AND ic.code_type IN ('CPT', 'HCPCS', 'MS-DRG', 'DRG') AND list_contains(?, ic.code)
    ORDER BY ic.code, ch.modifiers NULLS FIRST, ch.setting, ch.billing_class, ch.source_ref
"""


def charge_lines(con, extraction_id: str, codes: list[str]) -> list[compare.Line]:
    rows = con.execute(CHARGE_SQL, [extraction_id, codes]).fetchall()
    return [compare.Line(ct, code, tuple(others or []), d, setting, bc, mods, g, cash, mn, mx, ref, note)
            for ct, code, others, d, setting, bc, mods, g, cash, mn, mx, ref, note in rows]


def hospital_prices(con, service: catalog.Service, h: Hospital, disc: dict | None,
                    *, shown_lines: int | None = SHOWN_LINES, status: str | None = None,
                    detail: str = "") -> dict:
    """What this hospital charges for this service, with the comparability verdict.

    `status` overrides the verdict when something upstream already failed (a file that
    could not be read), so the reason travels with the result instead of being lost.
    """
    who = discovery.short_name(h)
    out = {
        "ccn": h.ccn, "name": who, "distance_km": round(h.distance_km, 1), "approximate": h.approximate,
        "url": (disc or {}).get("mrf_url"), "file_date": None, "verdict": status or NO_FILE,
        "detail": detail, "line_count": 0, "headline": None, "lines": [],
    }
    if status:
        return out
    if not (disc and disc["ok"]):
        out["detail"] = (disc or {}).get("reason") or "run `hpa locate` first"
        return out
    ext = scan.latest_extraction(con, disc["mrf_url"])
    if not ext:
        out["verdict"] = NOT_SCANNED
        return out
    out["file_date"] = ext.get("last_updated_on")
    lines = charge_lines(con, ext["extraction_id"], [code for _, code in service.codes])
    lines = compare.apply_review(lines, service.reviewed, who)
    s = compare.summarise(lines)
    out.update(
        verdict=s.verdict, detail=s.detail, line_count=len(lines),
        headline=line_dict(s.headline) if s.headline else None,
        lines=[line_dict(l) for l in (lines if shown_lines is None else lines[:shown_lines])],
    )
    return out


# --- the service a query means -----------------------------------------------------------

def resolve_service(query: str, *, service_id: str | None = None, con=None, use_llm: bool = True):
    """(service, resolution, note). `note` is what Claude said, or None when Claude was
    not asked. Claude may only choose among the resolver's candidates (SPEC)."""
    services = catalog.load()
    if service_id:
        s = next((x for x in services if x.id == service_id), None)
        if s is None:
            raise ValueError(f"no catalog entry with id {service_id}")
        return s, catalog.Resolution(catalog.SELECTED, s, (s,)), None
    r = catalog.resolve(query, services)
    if r.verdict == catalog.SELECTED:
        return r.service, r, None
    if use_llm and r.candidates and llm.have_api_key():
        service, why = llm.Claude(llm.make_client(), con).confirm_service(query, r)
        return service, r, why
    return None, r, None


def prices_payload(con, query: str, zips, ccn, limit, *, service_id=None, shown_lines=SHOWN_LINES,
                   use_llm: bool = True, llm_con=None) -> dict:
    """Prices from what is already stored: no network, no scanning. The read path shared
    by `hpa prices` and the server's /api/prices."""
    from hpa import targets

    service, r, note = resolve_service(query, service_id=service_id, con=llm_con, use_llm=use_llm)
    out = {"resolver": None if r.verdict == catalog.SELECTED else {"verdict": r.verdict, "reason": r.reason}, "note": note}
    if service is None:
        out.update(status="needs_clarification", candidates=[service_dict(c) for c in r.candidates])
        return out
    pairs = targets.located(con, zips, ccn, limit)
    out.update(status="ok", service=service_dict(service),
               hospitals=[hospital_prices(con, service, h, c, shown_lines=shown_lines) for h, c in pairs])
    return out


# --- a live run -------------------------------------------------------------------------

def run_search(con, zip_code: str, service: catalog.Service, emit: Emit, *, query: str | None = None,
               limit: int = 5, fresh: bool = False, force: bool = False, workers: int = 5,
               use_llm: bool = True, shown_lines: int | None = SHOWN_LINES) -> list[dict]:
    """Nearest hospitals -> located file -> scanned rows -> prices, hospitals in parallel.

    Every step reports through `emit`, and each hospital's result is emitted as soon as it
    is ready, so the wait is the slowest file rather than the sum of them.
    """
    hospitals = find_hospitals(con, zip_code, limit)
    emit("trace", text=f"nearest {len(hospitals)} hospitals to the centre of {zip_code}")
    for h in hospitals:
        miles = h.distance_km / KM_PER_MILE
        emit("trace", ccn=h.ccn, text=f"  {'~' if h.approximate else ''}{miles:.1f} mi  {discovery.short_name(h)}")
    reviewed = "reviewed" if service.reviewed else "unreviewed"
    emit("trace", text=f'"{query or service.name}" -> {service.name} ({service.code_list})  [mapping {reviewed}]')

    claude = None
    if use_llm and llm.have_api_key():
        # A DuckDB connection is not thread-safe; a cursor is a separate connection the
        # worker threads can use while other threads write.
        claude = llm.Claude(llm.make_client(), con.cursor())
    claude_lock = threading.Lock()  # one Claude call at a time keeps the trace readable

    results: dict[str, dict] = {}
    with httpx.Client() as client, ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_one_hospital, con.cursor(), client, h, service, emit, claude, claude_lock,
                        fresh, force, shown_lines): h
            for h in hospitals
        }
        for f in as_completed(futures):
            h = futures[f]
            try:
                r = f.result()
            except Exception as e:  # one hospital failing is a result, not a crashed run
                emit("trace", ccn=h.ccn, text=f"{discovery.short_name(h)}: {type(e).__name__}: {e}")
                r = hospital_prices(con, service, h, None, status=SCAN_FAILED, detail=f"{type(e).__name__}: {e}")
            results[h.ccn] = r
            emit("hospital", hospital=r)
    return [results[h.ccn] for h in hospitals]  # nearest first, whatever order they finished in


def _one_hospital(con, client, h: Hospital, service, emit: Emit, claude, claude_lock,
                  fresh: bool, force: bool, shown_lines) -> dict:
    who = discovery.short_name(h)

    def step(line: str) -> None:  # discovery prefixes the hospital itself
        emit("trace", ccn=h.ccn, text=line)

    def trace(line: str) -> None:
        emit("trace", ccn=h.ccn, text=f"{who}: {line}")

    def progress(phase: str, done: int, total: int | None) -> None:
        emit("progress", ccn=h.ccn, name=who, phase=phase, done=done, total=total)

    disc = None if fresh else store.cached_discovery(con, h.ccn)
    if disc:
        trace(f"cached result from {disc['discovered_at']:%Y-%m-%d}: "
              + (f"{disc['shape']} file at {disc['domain']}" if disc["ok"] else disc["reason"]))
    else:
        def serialised(fn):
            def call(*args):
                with claude_lock:
                    return fn(*args)
            return call

        tie_breaker = serialised(claude.pick_entry) if claude else None
        web_search = serialised(claude.find_hospital_website) if claude else None
        d = discovery.locate_price_file(client, h, step, tie_breaker, web_search)
        store.save_discovery(con, d)
        disc = store.cached_discovery(con, h.ccn)

    if not (disc and disc["ok"]):
        trace(f"no machine-readable file located — skipped ({disc['reason'] if disc else 'unknown'})")
        return hospital_prices(con, service, h, disc, shown_lines=shown_lines)

    with url_lock(disc["mrf_url"]):
        r = scan.scan(con, client, h.ccn, disc["mrf_url"], trace, force=force, progress=progress)
    if not r.ok:
        return hospital_prices(con, service, h, disc, shown_lines=shown_lines, status=SCAN_FAILED, detail=r.reason)
    return hospital_prices(con, service, h, disc, shown_lines=shown_lines)
