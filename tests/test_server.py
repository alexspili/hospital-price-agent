"""The API, with the network layers faked: no downloads, no Claude, no real files.

A fake `locate_price_file` and a fake `scan` stand in for discovery and extraction; the
rows they leave in the store are real, so the verdicts the endpoints return come from
compare.py exactly as they would in a live run.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hpa import discovery, mrf, pipeline, server, store
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


def fake_scan(con, client, ccn, url, trace, force=False, progress=None):
    from hpa.scan import ScanResult

    trace("downloading 1 MB (50%)")
    if progress:
        progress("download", 500_000, 1_000_000)
    trace("125,000 charges, 100,000 items so far")
    if progress:
        progress("extract", 125_000, None)
    store_extraction(con, url, ccn, cash=2735.80)
    return ScanResult(ccn, url, ok=True, checksum=f"sum{ccn}", extraction_id=f"ext{ccn}", charges=1, items=1)


@pytest.fixture
def api(con, monkeypatch):
    monkeypatch.setattr(pipeline.discovery, "locate_price_file", fake_locate)
    monkeypatch.setattr(pipeline.scan, "scan", fake_scan)
    monkeypatch.setattr(pipeline.llm, "have_api_key", lambda: False)  # no Claude in tests
    app = server.create_app(con, ":memory:")
    with TestClient(app) as tc:
        tc.app = app
        yield tc


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
    r = api.post("/api/runs", json={"zip": "77030", "service": "knee mri"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "started" and body["service"]["codes"] == "CPT 73721"

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
    def unlabelled(con_, client, ccn, url, trace, force=False, progress=None):
        from hpa.scan import ScanResult

        store_extraction(con_, url, ccn, cash=2735.80, billing_class=None)
        return ScanResult(ccn, url, ok=True, extraction_id=f"ext{ccn}", charges=1, items=1)

    monkeypatch.setattr(pipeline.scan, "scan", unlabelled)
    run_id = api.post("/api/runs", json={"zip": "77030", "service": "knee mri"}).json()["run_id"]
    result = next(e for e in events_of(api, run_id) if e["kind"] == "result")
    assert {h["verdict"] for h in result["hospitals"]} == {"unknown: no billing class stated", pipeline.NO_FILE}


def test_reconnecting_replays_only_what_was_missed(api):
    run_id = api.post("/api/runs", json={"zip": "77030", "service": "knee mri"}).json()["run_id"]
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
    for _ in range(server.MAX_ACTIVE_RUNS):
        api.post("/api/runs", json={"zip": "77030", "service": "knee mri"})
    for run in api.app.state.runs.values():
        run.status = "running"  # pin them: the fakes finish in milliseconds
    r = api.post("/api/runs", json={"zip": "77030", "service": "knee mri"})
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    assert "busy" in r.json()["detail"] and "try again" in r.json()["detail"]


def test_an_unknown_zip_is_rejected_before_any_work(api):
    r = api.post("/api/runs", json={"zip": "00000", "service": "knee mri"})
    assert r.status_code == 400 and "not a residential ZIP" in r.json()["detail"]
    assert api.app.state.runs == {}


def test_prices_reads_what_is_stored_without_scanning(api, con):
    store_extraction(con, URL.format(ccn="450289"), "450289", cash=1500.0)
    con.execute("INSERT INTO hospital_files VALUES ('450289', 'HARRIS', now(), true, 'cms-hpt', 'example.test', NULL, NULL, NULL, ?, 'csv-wide', 1000, NULL, NULL, NULL, '', '[]', 1.0)",
                [URL.format(ccn="450289")])
    body = api.get("/api/prices", params={"service": "knee mri", "zip": "77030"}).json()
    assert body["status"] == "ok" and body["service"]["codes"] == "CPT 73721"
    harris = next(h for h in body["hospitals"] if h["ccn"] == "450289")
    assert harris["verdict"] == "comparable" and harris["headline"]["cash"] == 1500.0
    # The others were never located, and nothing is invented for them.
    others = [h for h in body["hospitals"] if h["ccn"] != "450289"]
    assert [h["verdict"] for h in others] == [pipeline.NO_FILE] * len(others)
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
