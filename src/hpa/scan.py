"""Download a located price file and stream it into the store.

Freshness follows SPEC.md "Caching": a HEAD compares ETag / Last-Modified with the last
fetch; with no validators the header date decides; and nothing older than 30 days is
trusted regardless. The download streams to disk with a running checksum; extraction
streams from disk into DuckDB in batches. Peak memory is measured and stored.
"""

import csv
import hashlib
import resource
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from hpa import mrf
from hpa.discovery import USER_AGENT
from hpa.store import DATA_DIR

MRF_DIR = DATA_DIR / "mrf"
BATCH = 5000
MAX_AGE = timedelta(days=30)
Trace = Callable[[str], None]
# progress(phase, done, total): "download" counts bytes, "extract" counts charges. The
# page turns these into a moving counter; the CLI just prints the trace lines.
Progress = Callable[[str, int, int | None], None]


@dataclass
class ScanResult:
    ccn: str
    url: str
    ok: bool
    reason: str = ""
    checksum: str | None = None
    extraction_id: str | None = None
    charges: int = 0
    items: int = 0
    size_bytes: int = 0
    seconds: float = 0.0
    download_seconds: float = 0.0
    peak_rss_mb: float = 0.0
    cached: bool = False
    capped: bool = False  # not downloaded because the run's download budget was spent


def _rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / 1e6 if rss > 1e7 else rss / 1e3  # macOS reports bytes, Linux kilobytes


def _fmt_size(n: int) -> str:
    return f"{n / 1e6:,.0f} MB" if n >= 1_000_000 else f"{n / 1e3:,.0f} KB"


# --- freshness --------------------------------------------------------------------------

def latest_extraction(con, url: str) -> dict | None:
    """The newest successful extraction for this URL with the current parser, if any."""
    row = con.execute(
        """
        SELECT f.checksum, f.etag, f.last_modified, f.fetched_at, e.extraction_id, e.charges, e.items,
               fi.last_updated_on, f.size_bytes
        FROM fetches f
        JOIN extractions e ON e.checksum = f.checksum AND e.ok AND e.parser_version = ?
        LEFT JOIN files fi ON fi.checksum = f.checksum
        WHERE f.url = ? AND f.checksum IS NOT NULL
        ORDER BY f.fetched_at DESC LIMIT 1
        """,
        [mrf.PARSER_VERSION, url],
    ).fetchone()
    if not row:
        return None
    keys = ["checksum", "etag", "last_modified", "fetched_at", "extraction_id", "charges", "items", "last_updated_on", "size_bytes"]
    return dict(zip(keys, row))


def head_validators(client: httpx.Client, url: str) -> dict | None:
    """One HEAD per scan; both freshness checks read from it. None when it fails."""
    try:
        head = client.head(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20)
    except httpx.HTTPError as e:
        return {"error": type(e).__name__}
    if head.status_code >= 400:
        return {"error": f"HTTP {head.status_code}"}
    return {"etag": head.headers.get("etag"), "last_modified": head.headers.get("last-modified")}


def validators_match(prev: dict, head: dict | None) -> tuple[bool, str]:
    if head is None or head.get("error"):
        return False, f"HEAD failed ({head['error'] if head else '?'})"
    etag, lm = head.get("etag"), head.get("last_modified")
    if etag and prev["etag"]:
        # The stronger validator decides: a new ETag is a new file, whatever the date says.
        return (True, "same ETag") if etag == prev["etag"] else (False, "ETag changed")
    if lm and prev["last_modified"] and lm == prev["last_modified"]:
        return True, f"same Last-Modified ({lm})"
    if not etag and not lm:
        return False, "server sends no validators"
    return False, "validators changed"


def no_change_detected(prev: dict, head: dict | None) -> tuple[bool, str]:
    """True when the server's validators match the last fetch and it's under the max age."""
    if datetime.now() - prev["fetched_at"] > MAX_AGE:
        return False, "cached copy older than 30 days"
    same, why = validators_match(prev, head)
    return same, f"{why}, fetched {prev['fetched_at']:%Y-%m-%d}" if same else why


# --- download --------------------------------------------------------------------------

def reusable_download(con, url: str, head: dict | None):
    """A file downloaded earlier (even if its extraction failed or was interrupted) can be
    reused when it is still on disk and the server's validators haven't changed."""
    row = con.execute(
        "SELECT checksum, etag, last_modified, size_bytes, content_type, fetched_at FROM fetches "
        "WHERE url = ? AND checksum IS NOT NULL AND coalesce(reason, '') <> 'reused download' "
        "ORDER BY fetched_at DESC LIMIT 1", [url]
    ).fetchone()
    if not row:
        return None
    checksum, etag, lm, size, ctype, fetched_at = row
    # The same age rule as everywhere else: a copy older than 30 days is downloaded again,
    # however the validators read, and a reuse never counts as a fresh download.
    if datetime.now() - fetched_at > MAX_AGE:
        return None
    candidates = list(MRF_DIR.glob(f"{checksum}.*"))
    if not candidates or not validators_match({"etag": etag, "last_modified": lm}, head)[0]:
        return None
    return candidates[0], checksum, size, {"content-type": ctype, "etag": etag, "last-modified": lm}, 0.0


def download(client: httpx.Client, url: str, trace: Trace, progress: Progress | None = None) -> tuple[Path, str, int, dict, float]:
    """Stream to data/mrf/<sha256>.<ext>, hashing as it goes. Returns path, checksum, size,
    response headers and seconds."""
    MRF_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MRF_DIR / f"download.{time.time_ns()}.part"
    sha = hashlib.sha256()
    size = 0
    started = time.monotonic()
    last_report = started
    try:
        with client.stream("GET", url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            headers = dict(r.headers)
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    sha.update(chunk)
                    size += len(chunk)
                    now = time.monotonic()
                    if now - last_report >= 2:
                        pct = f" ({size / total:.0%})" if total else ""
                        trace(f"downloading {_fmt_size(size)}{pct}")
                        if progress:
                            progress("download", size, total or None)
                        last_report = now
    except BaseException:
        tmp.unlink(missing_ok=True)  # a partial file is worth nothing and costs disk
        raise
    checksum = sha.hexdigest()
    ext = mrf_ext(headers.get("content-type"), str(r.url), tmp)
    final = MRF_DIR / f"{checksum}.{ext}"
    tmp.replace(final)
    return final, checksum, size, headers, time.monotonic() - started


def mrf_ext(content_type: str | None, url: str, path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(4)
    if head.startswith(b"PK"):
        return "zip"
    if head.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"{"):
        return "json"
    return "csv"


# --- extraction -------------------------------------------------------------------------

# One extraction per (file, parser) at a time, whichever URL the file came from: the same
# bytes at two URLs share an extraction id, and a URL lock alone would not see that.
_extract_locks: dict[str, threading.Lock] = {}
_extract_locks_guard = threading.Lock()


def _extract_lock(extraction_id: str) -> threading.Lock:
    with _extract_locks_guard:
        return _extract_locks.setdefault(extraction_id, threading.Lock())


def extract(con, path: Path, checksum: str, size: int, trace: Trace, progress: Progress | None = None) -> tuple[str, int, int, float, float]:
    """Stream the file into items / item_codes / charges. Returns extraction id, charge
    count, item count, seconds and peak RSS in MB.

    Rows go through temporary CSV files that DuckDB bulk-loads at the end: its row-at-a-time
    `executemany` costs ~2 ms per row, which would make an 860 MB file an hours-long job.
    Streaming to disk keeps memory flat regardless of file size. Nothing already stored
    is touched until the whole file has parsed: an extraction that exists is replaced in
    one transaction, or not at all."""
    extraction_id = f"{checksum[:16]}-p{mrf.PARSER_VERSION}"
    with _extract_lock(extraction_id):
        return _extract(con, path, checksum, extraction_id, size, trace, progress)


def _extract(con, path: Path, checksum: str, extraction_id: str, size: int, trace: Trace, progress: Progress | None):
    started = time.monotonic()
    header, charges = mrf.open_mrf(str(path))
    con.execute("DELETE FROM files WHERE checksum = ?", [checksum])
    con.execute(
        "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, now())",
        [checksum, header.shape, header.version, header.hospital_name, header.last_updated_on,
         "; ".join(header.location_names), size],
    )

    seen_items: set[str] = set()
    n_charges = 0
    last_report = started
    with tempfile.TemporaryDirectory(dir=MRF_DIR) as tmp:
        paths = {t: Path(tmp) / f"{t}.csv" for t in ("items", "item_codes", "charges")}
        files = {t: open(p, "w", newline="", encoding="utf-8") for t, p in paths.items()}
        writers = {t: csv.writer(f, lineterminator="\n") for t, f in files.items()}
        try:
            for c in charges:
                n_charges += 1
                if c.item_id not in seen_items:
                    seen_items.add(c.item_id)
                    writers["items"].writerow((extraction_id, c.item_id, c.description, c.drug_unit, c.drug_type))
                    writers["item_codes"].writerows((extraction_id, c.item_id, t, code) for t, code in c.codes)
                charge_id = hashlib.sha1(f"{c.item_id}|{c.source_ref}".encode()).hexdigest()[:16]
                writers["charges"].writerow((extraction_id, charge_id, c.item_id, c.setting, c.billing_class, c.modifiers,
                                             c.gross, c.discounted_cash, c.minimum, c.maximum, c.notes, c.source_ref, c.off_template_note))
                now = time.monotonic()
                if now - last_report >= 2:
                    trace(f"{n_charges:,} charges, {len(seen_items):,} items so far")
                    if progress:
                        progress("extract", n_charges, None)
                    last_report = now
        finally:
            for f in files.values():
                f.close()
        parse_seconds = time.monotonic() - started
        # The parse is complete; now, and only now, the previous extraction of this file
        # gives way to it, all in one transaction.
        con.execute("BEGIN TRANSACTION")
        try:
            for table in ("items", "item_codes", "charges"):
                con.execute(f"DELETE FROM {table} WHERE extraction_id = ?", [extraction_id])
            con.execute("DELETE FROM extractions WHERE extraction_id = ?", [extraction_id])
            con.execute("INSERT INTO items SELECT * FROM read_csv(?, auto_detect = false, header = false, delim = ',', columns = "
                        "{'a': 'VARCHAR', 'b': 'VARCHAR', 'c': 'VARCHAR', 'd': 'VARCHAR', 'e': 'VARCHAR'}, nullstr = '')",
                        [str(paths["items"])])
            con.execute("INSERT INTO item_codes SELECT * FROM read_csv(?, auto_detect = false, header = false, delim = ',', columns = "
                        "{'a': 'VARCHAR', 'b': 'VARCHAR', 'c': 'VARCHAR', 'd': 'VARCHAR'}, nullstr = '')",
                        [str(paths["item_codes"])])
            con.execute("INSERT INTO charges SELECT * FROM read_csv(?, auto_detect = false, header = false, delim = ',', columns = "
                        "{'a': 'VARCHAR', 'b': 'VARCHAR', 'c': 'VARCHAR', 'd': 'VARCHAR', 'e': 'VARCHAR', 'f': 'VARCHAR', "
                        "'g': 'DOUBLE', 'h': 'DOUBLE', 'i': 'DOUBLE', 'j': 'DOUBLE', 'k': 'VARCHAR', 'l': 'VARCHAR', 'm': 'VARCHAR'}, nullstr = '')",
                        [str(paths["charges"])])
            seconds = time.monotonic() - started
            peak = _rss_mb()
            con.execute(
                "INSERT INTO extractions VALUES (?, ?, ?, now(), ?, ?, ?, ?, true, '')",
                [extraction_id, checksum, mrf.PARSER_VERSION, n_charges, len(seen_items), seconds, peak],
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    trace(f"parsed in {parse_seconds:.0f}s, loaded in {seconds - parse_seconds:.0f}s")
    return extraction_id, n_charges, len(seen_items), seconds, peak


# --- orchestration ------------------------------------------------------------------------

def scan(con, client: httpx.Client, ccn: str, url: str, trace: Trace, force: bool = False,
         progress: Progress | None = None, keep_download: bool = True,
         may_download: Callable[[], bool] | None = None) -> ScanResult:
    """`may_download` is asked once, right before a download would start: the run's
    budget is spent on downloads, not on files that turn out to be reusable."""
    started = time.monotonic()
    result = ScanResult(ccn, url, ok=False)
    prev = latest_extraction(con, url)
    known = con.execute("SELECT count(*) FROM fetches WHERE url = ? AND checksum IS NOT NULL", [url]).fetchone()[0]
    head = head_validators(client, url) if known and not force else None
    if prev and not force:
        same, why = no_change_detected(prev, head)
        if same:
            trace(f"no change detected ({why}), using cached {prev['charges']:,} charges")
            return ScanResult(ccn, url, True, why, prev["checksum"], prev["extraction_id"], prev["charges"], prev["items"],
                              prev["size_bytes"] or 0, time.monotonic() - started, cached=True)
        trace(f"re-downloading: {why}")

    on_disk = reusable_download(con, url, head)
    if on_disk and not force:
        path, checksum, size, headers, dl_seconds = on_disk
        trace(f"already downloaded ({_fmt_size(size)}, validators unchanged), extracting from disk")
        con.execute("INSERT INTO fetches VALUES (?, now(), 200, ?, ?, ?, ?, ?, ?, 0, 'reused download')",
                    [url, url, headers.get("content-type"), headers.get("etag"), headers.get("last-modified"), size, checksum])
        result.checksum, result.size_bytes = checksum, size
        try:
            result.extraction_id, result.charges, result.items, secs, result.peak_rss_mb = extract(con, path, checksum, size, trace, progress)
        except mrf.OffTemplate as e:
            result.reason = f"off-template: {e}"
            trace(result.reason)
            return result
        finally:
            if not keep_download:
                path.unlink(missing_ok=True)
        result.ok, result.seconds = True, time.monotonic() - started
        trace(f"{result.charges:,} charges, {result.items:,} items in {secs:.0f}s (peak {result.peak_rss_mb:.0f} MB)")
        return result

    if may_download is not None and not may_download():
        if prev:
            trace(f"download cap reached for this run; using the copy fetched {prev['fetched_at']:%Y-%m-%d}")
            return ScanResult(ccn, url, True, "download cap reached; older copy used", prev["checksum"], prev["extraction_id"],
                              prev["charges"], prev["items"], prev["size_bytes"] or 0, time.monotonic() - started, cached=True)
        result.reason, result.capped = "download cap reached for this run", True
        trace(result.reason)
        return result
    try:
        path, checksum, size, headers, dl_seconds = download(client, url, trace, progress)
    except httpx.HTTPError as e:
        reason = f"download failed: {getattr(e, 'response', None) and e.response.status_code or type(e).__name__}"
        con.execute("INSERT INTO fetches VALUES (?, now(), ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [url, getattr(getattr(e, "response", None), "status_code", None), None, None, None, None, None, None,
                     time.monotonic() - started, reason])
        trace(reason)
        result.reason = reason
        return result
    trace(f"downloaded {_fmt_size(size)} in {dl_seconds:.0f}s, sha256 {checksum[:12]}…")
    con.execute("INSERT INTO fetches VALUES (?, now(), 200, ?, ?, ?, ?, ?, ?, ?, '')",
                [url, url, headers.get("content-type"), headers.get("etag"), headers.get("last-modified"), size, checksum, dl_seconds])
    result.checksum, result.size_bytes, result.download_seconds = checksum, size, dl_seconds
    try:
        return _after_download(con, path, checksum, size, result, force, trace, progress, started)
    finally:
        if not keep_download:
            # The rows are in DuckDB; on a small host the multi-GB original is not worth the
            # disk, whichever way the extraction went. A later scan re-downloads it.
            path.unlink(missing_ok=True)


def _after_download(con, path: Path, checksum: str, size: int, result: ScanResult, force: bool,
                    trace: Trace, progress: Progress | None, started: float) -> ScanResult:
    existing = con.execute(
        "SELECT extraction_id, charges, items FROM extractions WHERE checksum = ? AND parser_version = ? AND ok",
        [checksum, mrf.PARSER_VERSION],
    ).fetchone()
    if existing and not force:
        trace(f"same file as before (checksum), {existing[1]:,} charges already extracted")
        result.ok, result.extraction_id, result.charges, result.items, result.cached = True, *existing, True
        result.seconds = time.monotonic() - started
        return result

    try:
        result.extraction_id, result.charges, result.items, secs, result.peak_rss_mb = extract(con, path, checksum, size, trace, progress)
    except mrf.OffTemplate as e:
        reason = f"off-template: {e}"
        con.execute("INSERT INTO extractions VALUES (?, ?, ?, now(), 0, 0, 0, 0, false, ?)",
                    [f"{checksum[:16]}-p{mrf.PARSER_VERSION}", checksum, mrf.PARSER_VERSION, reason])
        trace(reason)
        result.reason = reason
        return result
    result.ok = True
    result.seconds = time.monotonic() - started
    trace(f"{result.charges:,} charges, {result.items:,} items in {secs:.0f}s (peak {result.peak_rss_mb:.0f} MB)")
    return result
