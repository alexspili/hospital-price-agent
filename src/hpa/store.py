"""DuckDB store. One local file; nothing in it is ever committed."""

from pathlib import Path

import duckdb

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_DB = DATA_DIR / "hpa.duckdb"

# Reference tables (hospitals, zcta) are rebuilt by `hpa setup`. The price tables are
# filled from milestone 3 on: one row per scanned file, keyed by its checksum so a repeat
# area never rescans an unchanged file.
SCHEMA = """
CREATE TABLE IF NOT EXISTS price_files (
    checksum         VARCHAR PRIMARY KEY,
    ccn              VARCHAR NOT NULL,
    url              VARCHAR NOT NULL,
    template_version VARCHAR,
    last_updated_on  DATE,
    size_bytes       BIGINT,
    fetched_at       TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS price_rows (
    checksum         VARCHAR NOT NULL,
    code             VARCHAR NOT NULL,
    code_type        VARCHAR NOT NULL,
    description      VARCHAR,
    setting          VARCHAR,
    gross_charge     DECIMAL(14, 2),
    discounted_cash  DECIMAL(14, 2),
    min_negotiated   DECIMAL(14, 2),
    max_negotiated   DECIMAL(14, 2),
    -- Set when the file gives a percentage or algorithm instead of a dollar amount.
    -- Kept as text, never converted into dollars.
    non_dollar_note  VARCHAR
);
"""


def connect(path: Path | str = DEFAULT_DB) -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con
