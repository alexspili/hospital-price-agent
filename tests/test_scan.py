from pathlib import Path

import httpx
import pytest

from hpa import scan, store
from hpa.mrf import PARSER_VERSION

FIX = Path(__file__).parent / "fixtures" / "mrf"


@pytest.fixture
def con():
    return store.connect(":memory:")


@pytest.fixture
def mrf_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(scan, "MRF_DIR", tmp_path / "mrf")
    return tmp_path / "mrf"


def serving(body: bytes, headers: dict | None = None, status: int = 200):
    calls = []

    def handler(request):
        calls.append(request.method)
        h = {"content-type": "text/csv", "content-length": str(len(body)), **(headers or {})}
        if request.method == "HEAD":
            return httpx.Response(status, headers=h)
        return httpx.Response(status, headers=h, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_download_extract_and_store(con, mrf_dir):
    body = (FIX / "wide_elite.csv").read_bytes()
    client, calls = serving(body, {"etag": '"abc"', "last-modified": "Thu, 04 Jun 2026 12:21:27 GMT"})
    lines = []
    r = scan.scan(con, client, "670285", "https://x/elite.csv", lines.append)
    assert r.ok and not r.cached
    assert r.charges == 22 and r.items == 22 and r.size_bytes == len(body)
    assert (mrf_dir / f"{r.checksum}.csv").exists()
    assert con.execute("SELECT count(*) FROM charges").fetchone()[0] == 22
    assert con.execute("SELECT count(*) FROM item_codes WHERE code_type = 'CPT'").fetchone()[0] == 4
    f = con.execute("SELECT shape, template_version, hospital_name, last_updated_on FROM files").fetchone()
    assert f == ("csv-wide", "3.0.0", "23330 Emergency Center LLC", "6/1/2026")
    e = con.execute("SELECT parser_version, ok, charges FROM extractions").fetchone()
    assert e == (PARSER_VERSION, True, 22)
    assert any("downloaded" in line for line in lines) and any("22 charges" in line for line in lines)


def test_second_scan_uses_validators_and_skips_download(con, mrf_dir):
    body = (FIX / "wide_elite.csv").read_bytes()
    client, calls = serving(body, {"etag": '"abc"'})
    scan.scan(con, client, "670285", "https://x/elite.csv", lambda _: None)
    calls.clear()
    lines = []
    r = scan.scan(con, client, "670285", "https://x/elite.csv", lines.append)
    assert r.ok and r.cached and r.charges == 22
    assert calls == ["HEAD"]  # no GET
    assert lines == ["no change detected (same ETag, fetched " + lines[0].split("fetched ")[1]]


def test_changed_validator_redownloads_but_same_checksum_skips_extraction(con, mrf_dir):
    body = (FIX / "wide_elite.csv").read_bytes()
    client, _ = serving(body, {"etag": '"v1"'})
    scan.scan(con, client, "670285", "https://x/elite.csv", lambda _: None)
    client2, calls2 = serving(body, {"etag": '"v2"'})
    lines = []
    r = scan.scan(con, client2, "670285", "https://x/elite.csv", lines.append)
    assert r.ok and r.cached
    assert calls2 == ["HEAD", "GET"]
    assert any("same file as before (checksum)" in line for line in lines)
    assert con.execute("SELECT count(*) FROM extractions").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM fetches").fetchone()[0] == 2


def test_no_validators_forces_redownload(con, mrf_dir):
    body = (FIX / "wide_elite.csv").read_bytes()
    client, calls = serving(body)
    scan.scan(con, client, "670285", "https://x/elite.csv", lambda _: None)
    calls.clear()
    lines = []
    scan.scan(con, client, "670285", "https://x/elite.csv", lines.append)
    assert calls == ["HEAD", "GET"]
    assert lines[0] == "re-downloading: server sends no validators"


def test_off_template_file_is_recorded_as_failed_extraction(con, mrf_dir):
    client, _ = serving((FIX / "offtemplate_townsen.csv").read_bytes())
    lines = []
    r = scan.scan(con, client, "670266", "https://x/townsen.csv", lines.append)
    assert not r.ok and r.reason.startswith("off-template: row 3 is not the CMS header")
    assert con.execute("SELECT ok, reason FROM extractions").fetchone()[0] is False
    assert con.execute("SELECT count(*) FROM charges").fetchone()[0] == 0


def test_http_error_is_a_reason(con, mrf_dir):
    client, _ = serving(b"", status=403)
    r = scan.scan(con, client, "450804", "https://x/f.json", lambda _: None)
    assert not r.ok and r.reason == "download failed: 403"
    assert con.execute("SELECT status, reason FROM fetches").fetchone() == (403, "download failed: 403")


def test_json_with_bom_round_trips_into_the_store(con, mrf_dir):
    client, _ = serving((FIX / "methodist_items.json").read_bytes(), {"content-type": "application/octet-stream"})
    r = scan.scan(con, client, "450358", "https://x/f.ashx", lambda _: None)
    assert r.ok and r.charges == 10 and r.items == 7
    assert (scan.MRF_DIR / f"{r.checksum}.json").exists()
    rows = con.execute(
        "SELECT billing_class, modifiers, gross FROM charges ch JOIN item_codes ic USING (extraction_id, item_id) "
        "WHERE ic.code = '73721' ORDER BY source_ref"
    ).fetchall()
    assert rows == [("facility", None, 3200.0), ("professional", "26", 450.0)]


def test_interrupted_extraction_reuses_the_downloaded_file(con, mrf_dir):
    body = (FIX / "wide_elite.csv").read_bytes()
    client, calls = serving(body, {"etag": '"abc"'})
    # First attempt: the download completes and is recorded, but extraction never finishes.
    path, checksum, size, headers, _ = scan.download(client, "https://x/elite.csv", lambda _: None)
    con.execute("INSERT INTO fetches VALUES (?, now(), 200, ?, ?, ?, ?, ?, ?, 1, '')",
                ["https://x/elite.csv", "https://x/elite.csv", "text/csv", '"abc"', None, size, checksum])
    calls.clear()
    lines = []
    r = scan.scan(con, client, "670285", "https://x/elite.csv", lines.append)
    assert r.ok and r.charges == 22
    assert calls == ["HEAD"]  # no second GET
    assert lines[0].startswith("already downloaded")
