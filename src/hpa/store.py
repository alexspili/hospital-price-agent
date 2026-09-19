"""DuckDB store. One local file; nothing in it is ever committed.

Reference tables (`hospitals`, `zcta`) are rebuilt by `hpa setup`; everything else is
carried across rebuilds. The price tables arrive with milestone 3 and follow the
"Storage" section of SPEC.md.
"""

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_DB = DATA_DIR / "hpa.duckdb"
REFERENCE_TABLES = ("zcta", "hospitals")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    name VARCHAR, url VARCHAR, fetched_at TIMESTAMP, note VARCHAR
);
CREATE TABLE IF NOT EXISTS hospital_files (
    ccn VARCHAR, name VARCHAR, discovered_at TIMESTAMP, ok BOOLEAN, method VARCHAR,
    domain VARCHAR, index_url VARCHAR, location_name VARCHAR, source_page_url VARCHAR,
    mrf_url VARCHAR, shape VARCHAR, size_bytes BIGINT, last_modified VARCHAR, etag VARCHAR,
    content_type VARCHAR, reason VARCHAR, steps VARCHAR, seconds DOUBLE
);
CREATE TABLE IF NOT EXISTS fetches (
    url VARCHAR, fetched_at TIMESTAMP, status INTEGER, final_url VARCHAR, content_type VARCHAR,
    etag VARCHAR, last_modified VARCHAR, size_bytes BIGINT, checksum VARCHAR, seconds DOUBLE,
    reason VARCHAR
);
CREATE TABLE IF NOT EXISTS files (
    checksum VARCHAR PRIMARY KEY, shape VARCHAR, template_version VARCHAR, hospital_name VARCHAR,
    last_updated_on VARCHAR, location_names VARCHAR, size_bytes BIGINT, first_seen TIMESTAMP
);
CREATE TABLE IF NOT EXISTS extractions (
    extraction_id VARCHAR PRIMARY KEY, checksum VARCHAR, parser_version VARCHAR, extracted_at TIMESTAMP,
    charges BIGINT, items BIGINT, seconds DOUBLE, peak_rss_mb DOUBLE, ok BOOLEAN, reason VARCHAR
);
CREATE TABLE IF NOT EXISTS items (
    extraction_id VARCHAR, item_id VARCHAR, description VARCHAR, drug_unit VARCHAR, drug_type VARCHAR
);
CREATE TABLE IF NOT EXISTS item_codes (
    extraction_id VARCHAR, item_id VARCHAR, code_type VARCHAR, code VARCHAR
);
CREATE TABLE IF NOT EXISTS charges (
    extraction_id VARCHAR, charge_id VARCHAR, item_id VARCHAR, setting VARCHAR, billing_class VARCHAR,
    modifiers VARCHAR, gross DECIMAL(14, 2), discounted_cash DECIMAL(14, 2), minimum DECIMAL(14, 2),
    maximum DECIMAL(14, 2), notes VARCHAR, source_ref VARCHAR, off_template_note VARCHAR
);
CREATE TABLE IF NOT EXISTS llm_cache (
    key VARCHAR PRIMARY KEY, model VARCHAR, prompt_version VARCHAR, input VARCHAR,
    output VARCHAR, created_at TIMESTAMP
);
"""

SUCCESS_TTL = timedelta(days=30)
FAILURE_TTL = timedelta(days=7)


def connect(path: Path | str = DEFAULT_DB, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the store. A DuckDB file has one writer at a time, and no other process can
    open it at all while a writer holds it; see SPEC.md "Process model"."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA)
    return con


def save_discovery(con, d) -> None:
    p = d.probe
    e = d.entry
    con.execute(
        "INSERT INTO hospital_files VALUES (?, ?, now(), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            d.ccn, d.name, d.ok, d.method, d.domain, d.index_url,
            e.location_name if e else None, e.source_page_url if e else None, e.mrf_url if e else None,
            p.shape if p else None, p.size_bytes if p else None, p.last_modified if p else None,
            p.etag if p else None, p.content_type if p else None, d.reason, json.dumps(d.steps), d.seconds,
        ],
    )


def cached_discovery(con, ccn: str):
    """The latest stored result for a hospital, if still fresh. Returns the row as a dict."""
    row = con.execute(
        "SELECT * FROM hospital_files WHERE ccn = ? ORDER BY discovered_at DESC LIMIT 1", [ccn]
    ).fetchone()
    if row is None:
        return None
    cols = [c[0] for c in con.description]
    rec = dict(zip(cols, row))
    age = datetime.now() - rec["discovered_at"]
    if age > (SUCCESS_TTL if rec["ok"] else FAILURE_TTL):
        return None
    rec["steps"] = json.loads(rec["steps"] or "[]")
    return rec
