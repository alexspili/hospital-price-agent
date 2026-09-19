from pathlib import Path

import duckdb
import pytest

from hpa.build import BuildFailed, build_database

FIXTURES = Path(__file__).parent / "fixtures"


def test_failed_build_leaves_existing_database_untouched(tmp_path):
    db = tmp_path / "hpa.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE keep AS SELECT 42 AS answer")
    con.close()
    before = db.read_bytes()

    with pytest.raises(Exception):
        build_database(db, str(tmp_path / "missing.csv"), str(FIXTURES / "zcta.txt"), None)

    assert db.read_bytes() == before
    assert not (tmp_path / "hpa.duckdb.building").exists()
    assert duckdb.connect(str(db), read_only=True).execute("SELECT answer FROM keep").fetchone() == (42,)


def test_implausible_counts_are_rejected(tmp_path):
    # The fixtures are tiny, so a real build from them must fail validation.
    with pytest.raises(BuildFailed, match="implausible"):
        build_database(tmp_path / "hpa.duckdb", str(FIXTURES / "hospitals.csv"), str(FIXTURES / "zcta.txt"), None)
    assert not (tmp_path / "hpa.duckdb").exists()
