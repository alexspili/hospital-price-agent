"""DuckDB store. One local file; nothing in it is ever committed.

Reference tables (`hospitals`, `zcta`) are rebuilt by `hpa setup`. The price tables
arrive with milestone 3 and follow the "Storage" section of SPEC.md: file content, fetch
history and hospital-to-file links are separate tables, and every extracted row keeps the
context needed for a fair comparison (item id, billing class, modifiers, units).
"""

from pathlib import Path

import duckdb

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_DB = DATA_DIR / "hpa.duckdb"


def connect(path: Path | str = DEFAULT_DB, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the store. A DuckDB file has one writer at a time, so every query path opens
    read-only and only `hpa setup` (and, later, the scan worker) opens for writing."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)
