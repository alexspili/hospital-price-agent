"""DuckDB store. One local file; nothing in it is ever committed.

Reference tables (`hospitals`, `zcta`) are rebuilt by `hpa setup`; everything else is
carried across rebuilds. The price tables arrive with milestone 3 and follow the
"Storage" section of SPEC.md.
"""

import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

# Everything on disk lives under one directory: the database, raw reference downloads,
# price files and the server's marker. The container points it at the mounted disk.
DATA_DIR = Path(os.environ.get("HPA_DATA_DIR") or Path(__file__).resolve().parents[2] / "data")
DEFAULT_DB = DATA_DIR / "hpa.duckdb"
REFERENCE_TABLES = ("zcta", "hospitals")
# Tables whose primary key the code relies on (INSERT OR REPLACE, one row per key). A
# copy made with CREATE TABLE AS loses it, so copies are made from the schema instead.
KEYED_TABLES = ("files", "extractions", "llm_cache")

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
    -- DECIMAL(18, 6): some files carry sub-cent values (Harris Health: 5011.64785); store what is there.
    modifiers VARCHAR, gross DECIMAL(18, 6), discounted_cash DECIMAL(18, 6), minimum DECIMAL(18, 6),
    maximum DECIMAL(18, 6), notes VARCHAR, source_ref VARCHAR, off_template_note VARCHAR
);
CREATE TABLE IF NOT EXISTS llm_spend (
    called_at TIMESTAMP, model VARCHAR, fn VARCHAR, input_tokens BIGINT, output_tokens BIGINT,
    cache_read_tokens BIGINT, cache_write_tokens BIGINT, usd DOUBLE
);
CREATE TABLE IF NOT EXISTS llm_cache (
    key VARCHAR PRIMARY KEY, model VARCHAR, prompt_version VARCHAR, input VARCHAR,
    output VARCHAR, created_at TIMESTAMP
);
"""

# Columns added after the first databases were built. They arrive by migration rather
# than in the CREATEs above, so an existing store keeps its rows and gains the columns —
# and a rebuild, which carries the old tables over wholesale, must migrate them again.
MIGRATIONS = """
ALTER TABLE sources ADD COLUMN IF NOT EXISTS release_date VARCHAR;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS rows BIGINT;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS sha256 VARCHAR;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS size_bytes BIGINT;
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
        migrate(con)
    return con


def migrate(con) -> None:
    """Bring an existing store up to the current shape. Safe to run repeatedly."""
    con.execute(MIGRATIONS)
    restore_constraints(con)


def schema_tables() -> dict[str, str]:
    """{table name: its CREATE statement}, from SCHEMA."""
    out = {}
    for stmt in SCHEMA.split(";"):
        stmt = stmt.strip()
        if stmt.startswith("CREATE TABLE IF NOT EXISTS "):
            out[stmt.split()[5]] = stmt
    return out


def create_schema(con, catalog: str) -> None:
    """Apply SCHEMA and MIGRATIONS to an attached database, so a copy has the same
    tables, columns and keys as the original rather than a keyless CREATE TABLE AS."""
    con.execute(SCHEMA.replace("CREATE TABLE IF NOT EXISTS ", f"CREATE TABLE IF NOT EXISTS {catalog}."))
    con.execute(MIGRATIONS.replace("ALTER TABLE ", f"ALTER TABLE {catalog}."))


def copy_table(con, name: str, source: str, where: str = "", params: list | None = None) -> None:
    """Rows of `source` into the schema-shaped table `name`, keeping one row per key."""
    verb = "INSERT OR IGNORE" if name.split(".")[-1] in KEYED_TABLES else "INSERT"
    con.execute(f"{verb} INTO {name} SELECT * FROM {source}{(' WHERE ' + where) if where else ''}", params or [])


def restore_constraints(con) -> None:
    """A store whose keyed tables lost their primary key (an older export or rebuild
    copied them with CREATE TABLE AS) gets the key back, with duplicates dropped."""
    keyed = con.execute(
        "SELECT DISTINCT table_name FROM duckdb_constraints() WHERE constraint_type = 'PRIMARY KEY'"
    ).fetchall()
    have = {r[0] for r in keyed}
    creates = schema_tables()
    for table in KEYED_TABLES:
        if table in have:
            continue
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(f"CREATE TEMPORARY TABLE _rekey AS SELECT * FROM {table}")
            con.execute(f"DROP TABLE {table}")
            con.execute(creates[table])
            con.execute(f"INSERT OR IGNORE INTO {table} SELECT * FROM _rekey")
            con.execute("DROP TABLE _rekey")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise


def save_sources(con, records: list[dict]) -> None:
    """Where the reference data came from, one row per dataset per fetch. Never updated:
    a rebuild appends, so the provenance of what you had before is still there."""
    for r in records:
        con.execute(
            "INSERT INTO sources (name, url, fetched_at, note, release_date, rows, sha256, size_bytes) "
            "VALUES (?, ?, now(), ?, ?, ?, ?, ?)",
            [r["name"], r.get("url"), r.get("note", ""), r.get("release_date"),
             r.get("rows"), r.get("sha256"), r.get("size_bytes")],
        )


SOURCE_COLUMNS = ("name", "url", "fetched_at", "note", "release_date", "rows", "sha256", "size_bytes")


def sources(con) -> list[dict]:
    """The newest row per dataset. Counts printed anywhere come from here, never from a
    number typed into the code (SPEC "Behaviour rules").

    A database built before the provenance columns existed is read here too: it is only
    migrated when something opens it for writing, and a read-only reader should still get
    whatever rows it has.
    """
    have = {c[0] for c in con.execute("DESCRIBE sources").fetchall()}
    columns = [c for c in SOURCE_COLUMNS if c in have]
    rows = con.execute(f"""
        SELECT {", ".join(columns)} FROM sources
        QUALIFY row_number() OVER (PARTITION BY name ORDER BY fetched_at DESC) = 1
        ORDER BY name
    """).fetchall()
    return [{**{k: None for k in SOURCE_COLUMNS}, **dict(zip(columns, r))} for r in rows]


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


def cached_discovery(con, ccn: str, within_ttl: bool = True):
    """The latest stored result for a hospital, as a dict.

    With `within_ttl` (a live run deciding whether to look again) a result past its TTL
    is None. A read path passes False: what was found and scanned is still the evidence
    on hand, however old the discovery, and the row says so with `stale`.
    """
    row = con.execute(
        "SELECT * FROM hospital_files WHERE ccn = ? ORDER BY discovered_at DESC LIMIT 1", [ccn]
    ).fetchone()
    if row is None:
        return None
    cols = [c[0] for c in con.description]
    rec = dict(zip(cols, row))
    age = datetime.now() - rec["discovered_at"]
    rec["stale"] = age > (SUCCESS_TTL if rec["ok"] else FAILURE_TTL)
    if rec["stale"] and within_ttl:
        return None
    rec["steps"] = json.loads(rec["steps"] or "[]")
    return rec
