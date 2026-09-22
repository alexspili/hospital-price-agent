"""The API, with the network layers faked: no downloads, no Claude, no real files.

A fake `locate_price_file` and a fake `scan` stand in for discovery and extraction; the
rows they leave in the store are real, so the verdicts the endpoints return come from
compare.py exactly as they would in a live run.
"""

import json
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hpa import discovery, mrf, pipeline, server, store
from hpa import settings as settings_module
from hpa.geo import load_zcta
from hpa.hospitals import load_hospitals

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://example.test/{ccn}/standardcharges.csv"

# One hospital that answers with a price file, one that has none: both keep their slot.
NO_FILE_CCN = "450068"


@pytest.fixture
def con():
    con = store.connect(":memory:")
    load_zcta(con, str(FIXTURES / "zcta.txt"))
    load_hospitals(con, str(FIXTURES / "hospitals.csv"), str(FIXTURES / "coords.csv"))
    return con


def fake_locate(client, hospital, trace=lambda line: None, tie_breaker=None, web_search=None):
    who = discovery.short_name(hospital)
    if hospital.ccn == NO_FILE_CCN:
        trace(f"{who}: no cms-hpt.txt on any guessed domain")
        return discovery.Discovery(hospital.ccn, hospital.name, "failed", reason="no index and no linked file",
                                   steps=["no cms-hpt.txt on any guessed domain"])
    url = URL.format(ccn=hospital.ccn)
    trace(f"{who}: cms-hpt.txt found at https://example.test/cms-hpt.txt")
    return discovery.Discovery(
        hospital.ccn, hospital.name, "cms-hpt", domain="example.test", index_url="https://example.test/cms-hpt.txt",
        entry=discovery.HptEntry(location_name=hospital.name, source_page_url="https://example.test/prices", mrf_url=url),
        probe=discovery.Probe(url=url, ok=True, status_code=200, final_url=url, content_type="text/csv",
                              size_bytes=1_000_000, last_modified="Wed, 09 Sep 2026 00:00:00 GMT", etag='"abc"',
                              shape="csv-wide", reason=""),
        steps=["cms-hpt.txt found at https://example.test/cms-hpt.txt"],
    )


def store_extraction(con, url: str, ccn: str, cash: float | None, billing_class: str | None = "facility") -> None:
    """The rows a real scan would have left behind for CPT 73721."""
    checksum, ext = f"sum{ccn}", f"ext{ccn}"
    con.execute("INSERT INTO fetches VALUES (?, now(), 200, ?, 'text/csv', '\"abc\"', 'Wed, 09 Sep 2026 00:00:00 GMT', 1000000, ?, 1.0, '')",
                [url, url, checksum])
    con.execute("INSERT OR REPLACE INTO files VALUES (?, 'csv-wide', '3.0.0', ?, '2026-09-01', '', 1000000, now())", [checksum, ccn])
    con.execute("INSERT INTO extractions VALUES (?, ?, ?, now(), 1, 1, 1.0, 100.0, true, '')", [ext, checksum, mrf.PARSER_VERSION])
    con.execute("INSERT INTO items VALUES (?, 'i1', 'MRI JOINT LOWER EXTREMITY W/O CONTRAST', NULL, NULL)", [ext])
    con.execute("INSERT INTO item_codes VALUES (?, 'i1', 'CPT', '73721')", [ext])
    con.execute("INSERT INTO charges VALUES (?, 'c1', 'i1', 'outpatient', ?, NULL, 5471.59, ?, 431.06, 574.74, NULL, 'row 1570', NULL)",
                [ext, billing_class, cash])


def fake_scan(con, client, ccn, url, trace, force=False, progress=None, keep_download=True, may_download=None):
    from hpa.scan import ScanResult

    trace("downloading 1 MB (50%)")
    if progress:
        progress("download", 500_000, 1_000_000)
    trace("125,000 charges, 100,000 items so far")
    if progress:
        progress("extract", 125_000, None)
    store_extraction(con, url, ccn, cash=2735.80)
    return ScanResult(ccn, url, ok=True, checksum=f"sum{ccn}", extraction_id=f"ext{ccn}", charges=1, items=1)


@contextmanager
def serving(con, monkeypatch, **limits):
    monkeypatch.setattr(pipeline.discovery, "locate_price_file", fake_locate)
    monkeypatch.setattr(pipeline.scan, "scan", fake_scan)
    monkeypatch.setattr(pipeline.llm, "have_api_key", lambda: False)  # no Claude in tests
    app = server.create_app(con, ":memory:", settings_module.Settings(**limits))
    with TestClient(app) as tc:
        tc.app = app
        try:
            yield tc
        finally:
            drain(tc)


def drain(tc: TestClient, timeout: float = 10.0) -> None:
    """Let every started run finish before the test ends.

    A run is a background thread: if the test walks away while one is going, monkeypatch
    puts the real `locate_price_file` back underneath it and the thread goes to the actual
    network — which is how an offline suite ends up hanging on a socket.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(run.status != "running" for run in tc.app.state.runs.values()):
            return
        time.sleep(0.02)
    raise AssertionError("a run was still going when the test ended")


@pytest.fixture
def api(con, monkeypatch):
    with serving(con, monkeypatch) as tc:
        yield tc


def live_run(tc: TestClient, zip_code: str = "77030", service: str = "knee mri", **extra):
    return tc.post("/api/runs", json={"zip": zip_code, "service": service, "live": True, **extra})


def events_of(tc: TestClient, run_id: str, after: int = 0) -> list[dict]:
    got = []
    with tc.stream("GET", f"/api/runs/{run_id}/events", params={"after": after}, timeout=30) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: "):
                got.append(json.loads(line[6:]))
    return got


def test_a_run_streams_its_trace_and_ends_with_the_result(api):
    r = live_run(api)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "started" and body["service"]["codes"] == "CPT 73721" and body["live"]

    events = events_of(api, body["run_id"])
    kinds = [e["kind"] for e in events]
    assert kinds[-1] == "end" and kinds[-2] == "result"
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))

    trace = [e["text"] for e in events if e["kind"] == "trace"]
    assert trace[0] == "nearest 5 hospitals to the centre of 77030"
    assert any('"knee mri" -> MRI scan of leg joint (CPT 73721)' in line for line in trace)
    assert any("cms-hpt.txt found" in line for line in trace)

    # A moving row counter, not a spinner (SPEC "Behaviour rules").
    assert [e["phase"] for e in events if e["kind"] == "progress"][:2] == ["download", "extract"]

    result = next(e for e in events if e["kind"] == "result")
    assert len(result["hospitals"]) == 5
    priced = [h for h in result["hospitals"] if h["verdict"] == "comparable"]
    assert priced and priced[0]["headline"]["cash"] == 2735.80
    assert priced[0]["headline"]["ref"] == "row 1570" and priced[0]["file_date"] == "2026-09-01"
    assert priced[0]["url"].startswith("https://example.test/")

    # The hospital without a file keeps its slot and says why.
    missing = next(h for h in result["hospitals"] if h["ccn"] == NO_FILE_CCN)
    assert missing["verdict"] == pipeline.NO_FILE and missing["detail"] == "no index and no linked file"


def test_a_missing_billing_class_is_unknown_not_a_guess(api, con, monkeypatch):
    def unlabelled(con_, client, ccn, url, trace, force=False, progress=None, keep_download=True, may_download=None):
        from hpa.scan import ScanResult

        store_extraction(con_, url, ccn, cash=2735.80, billing_class=None)
        return ScanResult(ccn, url, ok=True, extraction_id=f"ext{ccn}", charges=1, items=1)

    monkeypatch.setattr(pipeline.scan, "scan", unlabelled)
    run_id = live_run(api).json()["run_id"]
    result = next(e for e in events_of(api, run_id) if e["kind"] == "result")
    assert {h["verdict"] for h in result["hospitals"]} == {"unknown: no billing class stated", pipeline.NO_FILE}


def test_reconnecting_replays_only_what_was_missed(api):
    run_id = live_run(api).json()["run_id"]
    everything = events_of(api, run_id)
    again = events_of(api, run_id, after=3)
    assert [e["seq"] for e in again] == [e["seq"] for e in everything[3:]]

    state = api.get(f"/api/runs/{run_id}").json()
    assert state["status"] == "done" and len(state["events"]) == len(everything)
    assert state["result"]["hospitals"] == next(e for e in everything if e["kind"] == "result")["hospitals"]


def test_an_unclear_service_asks_instead_of_scanning(api):
    r = api.post("/api/runs", json={"zip": "77030", "service": "knee mri with contrast"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "needs_clarification" and body["verdict"] == "unsupported variant"
    assert body["candidates"] and not body["asked_claude"]
    assert api.app.state.runs == {}  # nothing was scanned on a guess


def test_answering_with_a_candidate_starts_the_run(api):
    ask = api.post("/api/runs", json={"zip": "77030", "service": "knee mri with contrast"}).json()
    chosen = ask["candidates"][0]
    r = api.post("/api/runs", json={"zip": "77030", "service_id": chosen["id"]})
    assert r.status_code == 202 and r.json()["service"]["id"] == chosen["id"]


def test_a_third_run_is_told_the_server_is_busy(api):
    # Runs held open by hand: a real one with fakes behind it finishes in milliseconds,
    # which would make this a race rather than a test of the gate.
    for i in range(server.MAX_ACTIVE_RUNS):
        held = server.Run(id=f"held{i}", zip="77030", query="knee mri", service={}, loop=api.app.state.loop)
        api.app.state.runs[held.id] = held
    r = api.post("/api/runs", json={"zip": "77030", "service": "knee mri"})
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    assert "busy" in r.json()["detail"] and "try again" in r.json()["detail"]
    for held in list(api.app.state.runs.values()):
        held.status = "done"  # nothing is executing them; let the drain finish


def test_an_unknown_zip_is_rejected_before_any_work(api):
    r = api.post("/api/runs", json={"zip": "00000", "service": "knee mri"})
    assert r.status_code == 400 and "not a residential ZIP" in r.json()["detail"]
    assert api.app.state.runs == {}


def test_prices_reads_what_is_stored_without_scanning(api, con):
    store_extraction(con, URL.format(ccn="450289"), "450289", cash=1500.0)
    con.execute("INSERT INTO hospital_files VALUES ('450289', 'HARRIS', now(), true, 'cms-hpt', 'example.test', NULL, NULL, NULL, ?, 'csv-wide', 1000, NULL, NULL, NULL, '', '[]', 1.0, NULL)",
                [URL.format(ccn="450289")])
    body = api.get("/api/prices", params={"service": "knee mri", "zip": "77030"}).json()
    assert body["status"] == "ok" and body["service"]["codes"] == "CPT 73721"
    harris = next(h for h in body["hospitals"] if h["ccn"] == "450289")
    assert harris["verdict"] == "comparable" and harris["headline"]["cash"] == 1500.0
    # The others were never located, and nothing is invented for them.
    others = [h for h in body["hospitals"] if h["ccn"] != "450289"]
    assert [h["verdict"] for h in others] == [pipeline.NOT_LOOKED] * len(others)
    assert all(h["headline"] is None for h in others)


def test_prices_asks_rather_than_choosing(api):
    body = api.get("/api/prices", params={"service": "knee mri with contrast", "zip": "77030"}).json()
    assert body["status"] == "needs_clarification" and body["candidates"]


def test_the_recorded_run_is_served_in_the_same_shape(api):
    index = api.get("/api/demo").json()
    assert index["zips"] and index["services"]
    zip_code, query = index["zips"][0], index["services"][0]["query"]

    body = api.get("/api/demo", params={"zip": zip_code, "service": query}).json()
    assert body["status"] == "recorded"
    assert [e["kind"] for e in body["events"]][-2:] == ["result", "end"]
    assert body["result"]["hospitals"] and all("verdict" in h for h in body["result"]["hospitals"])
    assert all(set(h) >= {"ccn", "name", "verdict", "headline", "url"} for h in body["result"]["hospitals"])


def test_health_says_who_holds_the_database(api):
    body = api.get("/api/health").json()
    assert body["status"] == "ok" and body["db"] == ":memory:" and body["runs_active"] == 0


# --- what the hosted demo is allowed to do (SPEC "Hosted demo constraints") --------------

def boom(*a, **k):  # any call means the network was touched when it should not have been
    raise AssertionError("a cache-first run must not scan")


def test_the_default_run_reads_only_what_is_stored(api, con, monkeypatch):
    store_extraction(con, URL.format(ccn="450289"), "450289", cash=1500.0)
    con.execute("INSERT INTO hospital_files VALUES ('450289', 'HARRIS', now(), true, 'cms-hpt', 'example.test', NULL, NULL, NULL, ?, 'csv-wide', 1000, NULL, NULL, NULL, '', '[]', 1.0, NULL)",
                [URL.format(ccn="450289")])
    monkeypatch.setattr(pipeline.scan, "scan", boom)
    monkeypatch.setattr(pipeline.discovery, "locate_price_file", boom)

    body = api.post("/api/runs", json={"zip": "77030", "service": "knee mri"}).json()
    assert body["live"] is False
    events = events_of(api, body["run_id"])
    result = next(e for e in events if e["kind"] == "result")

    harris = next(h for h in result["hospitals"] if h["ccn"] == "450289")
    assert harris["verdict"] == "comparable" and harris["headline"]["cash"] == 1500.0
    others = [h for h in result["hospitals"] if h["ccn"] != "450289"]
    assert all(h["verdict"] == pipeline.NOT_LOOKED and h["headline"] is None for h in others)
    assert any("no downloads, no model calls" in e.get("text", "") for e in events)
    assert any("run live" in e.get("text", "") for e in events)


def test_a_live_run_needs_the_pin_when_one_is_set(con, monkeypatch):
    with serving(con, monkeypatch, live_pin="hunter2") as api:
        assert api.get("/api/config").json()["live_needs_pin"] is True
        # The pre-scanned answer is open to everyone.
        assert api.post("/api/runs", json={"zip": "77030", "service": "knee mri"}).status_code == 202

        refused = live_run(api)
        assert refused.status_code == 403 and "password" in refused.json()["detail"]
        assert live_run(api, pin="wrong").status_code == 403
        assert live_run(api, pin="hunter2").status_code == 202


def test_live_runs_are_rate_limited_per_address(con, monkeypatch):
    with serving(con, monkeypatch, runs_per_hour=1) as api:
        assert live_run(api).status_code == 202
        refused = live_run(api)
        assert refused.status_code == 429 and int(refused.headers["retry-after"]) > 0
        assert "limited to 1 an hour" in refused.json()["detail"]
        # A cache-first run costs nothing and is never rate limited.
        assert api.post("/api/runs", json={"zip": "77030", "service": "knee mri"}).status_code == 202


def test_a_run_downloads_no_more_files_than_its_cap(con, monkeypatch):
    with serving(con, monkeypatch, max_downloads=2) as api:
        result = next(e for e in events_of(api, live_run(api).json()["run_id"]) if e["kind"] == "result")
        scanned = [h for h in result["hospitals"] if h["verdict"] == "comparable"]
        capped = [h for h in result["hospitals"] if "download cap" in h["detail"]]
        assert len(scanned) == 2
        assert len(capped) == 2 and all(h["headline"] is None for h in capped)  # the fifth has no file at all


def test_the_rate_limiter_forgets_an_address_after_the_window():
    limiter = server.RateLimit(per_hour=2, window=60)
    assert limiter.take("1.2.3.4", now=0) is None
    assert limiter.take("1.2.3.4", now=1) is None
    assert limiter.take("1.2.3.4", now=2) == 58
    assert limiter.take("5.6.7.8", now=2) is None  # a different address is unaffected
    assert limiter.take("1.2.3.4", now=61) is None


def test_the_client_ip_comes_from_the_proxy_only_when_trusted(api):
    from hpa.settings import Settings

    class FakeRequest:
        headers = {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}
        client = type("C", (), {"host": "10.0.0.1"})()

    assert server._client_ip(FakeRequest(), Settings(trust_proxy=True)) == "203.0.113.9"
    assert server._client_ip(FakeRequest(), Settings(trust_proxy=False)) == "10.0.0.1"


# --- nothing unauthenticated may spend money --------------------------------------------

def no_claude_please(*a, **k):
    raise AssertionError("an unauthenticated request must never reach Claude")


def test_a_cache_first_run_never_calls_claude(con, monkeypatch):
    """The PIN gates scanning; it must also gate spending. Otherwise a stranger could
    burn the daily model budget by typing ambiguous service names."""
    monkeypatch.setattr(pipeline.llm, "have_api_key", lambda: True)
    monkeypatch.setattr(pipeline.llm, "Claude", no_claude_please)
    with serving(con, monkeypatch, live_pin="hunter2") as api:
        monkeypatch.setattr(pipeline.llm, "have_api_key", lambda: True)  # serving() reset it
        body = api.post("/api/runs", json={"zip": "77030", "service": "knee mri with contrast"}).json()
        assert body["status"] == "needs_clarification" and body["asked_claude"] is False
        assert body["candidates"]  # the resolver's own answer, for free

        priced = api.get("/api/prices", params={"service": "knee mri with contrast", "zip": "77030"}).json()
        assert priced["status"] == "needs_clarification" and priced["note"] is None


def test_the_recorded_run_says_whose_prices_and_whether_they_compare(api):
    """The landing page is the recording, so it must carry what a live run carries: the
    hospital's type (a children's hospital's price says so) and a verdict on every pair."""
    index = api.get("/api/demo").json()
    body = api.get("/api/demo", params={"zip": index["zips"][0], "service": index["services"][0]["query"]}).json()
    hospitals = body["result"]["hospitals"]
    assert all(h.get("hospital_type") for h in hospitals)
    assert any(h["hospital_type"] != "Acute Care Hospitals" for h in hospitals)  # Texas Children's, at 77030
    n = len(hospitals)
    pairs = body["result"]["comparisons"]
    assert len(pairs) == n * (n - 1) // 2
    assert {p["verdict"] for p in pairs} <= {"comparable", "not comparable", "unknown"}
    assert body["events"][-2]["comparisons"] == pairs  # the result event carries the same


def test_the_catalog_is_served_for_a_query_that_matched_nothing(api):
    services = api.get("/api/catalog").json()
    assert len(services) == 70
    assert all({"id", "name", "codes", "reviewed"} <= set(s) for s in services)
    assert any(s["id"] == "cpt-73721" for s in services)


def test_prices_by_service_id_returns_every_line(api, con):
    store_extraction(con, URL.format(ccn="450289"), "450289", cash=1500.0)
    con.execute("INSERT INTO hospital_files VALUES ('450289', 'HARRIS', now(), true, 'cms-hpt', 'example.test', NULL, NULL, NULL, ?, 'csv-wide', 1000, NULL, NULL, NULL, '', '[]', 1.0, NULL)",
                [URL.format(ccn="450289")])
    body = api.get("/api/prices", params={"service_id": "cpt-73721", "zip": "77030", "all": "true"}).json()
    assert body["status"] == "ok" and body["service"]["id"] == "cpt-73721"
    harris = next(h for h in body["hospitals"] if h["ccn"] == "450289")
    assert len(harris["lines"]) == harris["line_count"] == 1
    assert api.get("/api/prices", params={"zip": "77030"}).status_code == 400
    assert api.get("/api/prices", params={"service_id": "cpt-00000", "zip": "77030"}).status_code == 400


def test_a_public_host_refuses_to_serve_without_its_pin(con):
    import pytest as _pytest

    with _pytest.raises(ValueError, match="HPA_REQUIRE_PIN"):
        server.create_app(con, ":memory:", settings_module.Settings(require_pin=True))
    assert settings_module.from_env({"HPA_REQUIRE_PIN": "1", "HPA_LIVE_PIN": ""}).require_pin
    settings_module.from_env({"HPA_REQUIRE_PIN": "1", "HPA_LIVE_PIN": "s3cret"}).check()


def test_finished_runs_are_forgotten_after_the_replay_window(api):
    body = api.post("/api/runs", json={"zip": "77030", "service": "knee mri"}).json()
    events_of(api, body["run_id"])
    drain(api)
    assert api.get(f"/api/runs/{body['run_id']}").status_code == 200
    run = api.app.state.runs[body["run_id"]]
    server._forget_finished(api.app, now=run.finished_at + server.RUN_RETENTION + 1)
    assert api.get(f"/api/runs/{body['run_id']}").status_code == 404


def test_the_password_is_a_word_so_its_case_does_not_matter():
    assert server._password_ok("Hospital", "hospital")
    assert server._password_ok(" hospital ", "Hospital")
    assert not server._password_ok("hospitals", "hospital")
    assert not server._password_ok(None, "hospital")


def test_a_live_request_is_turned_away_before_it_can_consult_claude(api, monkeypatch):
    """Service resolution happens before a run is admitted; a full server refuses the
    live request first, so model calls stay bounded by the run limit."""
    first, second = live_run(api).json(), live_run(api).json()
    assert first["status"] == second["status"] == "started"

    def boom(*a, **k):
        raise AssertionError("resolved a service for a request the server should have refused")

    monkeypatch.setattr(pipeline, "resolve_service", boom)
    assert live_run(api, service="mri").status_code == 429
    drain(api)


def test_the_recorded_run_explains_its_codes_too(api):
    index = api.get("/api/demo").json()
    body = api.get("/api/demo", params={"zip": index["zips"][0], "service": index["services"][0]["query"]}).json()
    lines = [l for h in body["result"]["hospitals"] for l in h["lines"]]
    assert lines and all(l.get("explained") for l in lines)
    assert any(any(v.startswith("Revenue code") for v in l["explained"].values()) for l in lines)
    # A recording made before codes were explained is explained on the way out.
    old = {**server.demo_run.__globals__["json"].loads(server.demo.DEMO_FILE.read_text())}
    for e in old["services"].values():
        for h in e["hospitals"]:
            for l in h["lines"]:
                l.pop("explained", None)
    r = server.demo_run(old, index["zips"][0], index["services"][0]["query"])["result"]
    assert all(l.get("explained") for h in r["hospitals"] for l in h["lines"])
