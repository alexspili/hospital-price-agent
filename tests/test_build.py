import threading
from pathlib import Path

import duckdb
import pytest

from hpa.build import BuildFailed, SetupInProgress, build_database, setup_lock
from hpa.hospitals import find_hospitals

FIXTURES = Path(__file__).parent / "fixtures"
SMALL = dict(min_zips=1, min_hospitals=1, max_unresolved_share=1.0)  # the fixtures are tiny


def test_failed_build_leaves_existing_database_untouched(tmp_path):
    db = tmp_path / "hpa.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE keep AS SELECT 42 AS answer")
    con.close()
    before = db.read_bytes()

    with pytest.raises(Exception):
        build_database(db, str(tmp_path / "missing.csv"), str(FIXTURES / "zcta.txt"), None)

    assert db.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["hpa.duckdb"]
    assert duckdb.connect(str(db), read_only=True).execute("SELECT answer FROM keep").fetchone() == (42,)


def test_successful_build_can_be_reopened_and_queried(tmp_path):
    db = tmp_path / "hpa.duckdb"
    result = build_database(
        db, str(FIXTURES / "hospitals.csv"), str(FIXTURES / "zcta.txt"), str(FIXTURES / "coords.csv"), **SMALL
    )
    assert result["hospitals"] == 12 and result["address"] == 9
    assert [p.name for p in tmp_path.iterdir()] == ["hpa.duckdb"]
    con = duckdb.connect(str(db), read_only=True)
    nearest = find_hospitals(con, "77030", limit=3)
    assert {h.ccn for h in nearest} == {"450289", "450068", "450035"}


def test_implausible_counts_are_rejected(tmp_path):
    with pytest.raises(BuildFailed, match="implausible"):
        build_database(tmp_path / "hpa.duckdb", str(FIXTURES / "hospitals.csv"), str(FIXTURES / "zcta.txt"), None)
    assert not (tmp_path / "hpa.duckdb").exists()


def test_failed_geocoding_is_not_the_same_as_skipping_it(tmp_path):
    # An empty coordinates file (what a silently broken geocoder run would produce) must
    # not build a centroid-only database while claiming geocoding happened.
    empty = tmp_path / "coords.csv"
    empty.write_text("ccn,lat,lon,match\n")
    with pytest.raises(BuildFailed, match="located by address"):
        build_database(tmp_path / "hpa.duckdb", str(FIXTURES / "hospitals.csv"), str(FIXTURES / "zcta.txt"), str(empty), **SMALL)
    # Explicitly skipping geocoding is fine.
    build_database(tmp_path / "hpa.duckdb", str(FIXTURES / "hospitals.csv"), str(FIXTURES / "zcta.txt"), None, **SMALL)


def test_database_held_open_elsewhere_is_not_replaced(tmp_path):
    db = tmp_path / "hpa.duckdb"
    build_database(db, str(FIXTURES / "hospitals.csv"), str(FIXTURES / "zcta.txt"), None, **SMALL)
    holder = duckdb.connect(str(db))  # simulates the server owning the file
    try:
        with pytest.raises(BuildFailed, match="open in another process"):
            build_database(db, str(FIXTURES / "hospitals.csv"), str(FIXTURES / "zcta.txt"), None, **SMALL)
    finally:
        holder.close()
    assert [p.name for p in tmp_path.iterdir()] == ["hpa.duckdb"]


def test_second_setup_is_refused_while_the_first_holds_the_lock(tmp_path):
    db = tmp_path / "hpa.duckdb"
    entered, release = threading.Event(), threading.Event()

    def first():
        with setup_lock(db):
            entered.set()
            release.wait()

    t = threading.Thread(target=first)
    t.start()
    entered.wait()
    try:
        with pytest.raises(SetupInProgress):
            with setup_lock(db):
                pass
    finally:
        release.set()
        t.join()
    with setup_lock(db):  # free again
        pass
