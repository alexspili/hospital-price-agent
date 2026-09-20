import subprocess
import sys
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


def test_database_held_open_by_another_process_is_not_replaced(tmp_path):
    # DuckDB shares one instance within a process, so the holder must be a real second
    # process, as the server would be.
    db = tmp_path / "hpa.duckdb"
    build_database(db, str(FIXTURES / "hospitals.csv"), str(FIXTURES / "zcta.txt"), None, **SMALL)
    holder = subprocess.Popen(
        [sys.executable, "-c", f"import duckdb, sys; c = duckdb.connect({str(db)!r}); print('held', flush=True); sys.stdin.readline()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(BuildFailed, match="open in another process"):
            build_database(db, str(FIXTURES / "hospitals.csv"), str(FIXTURES / "zcta.txt"), None, **SMALL)
    finally:
        holder.stdin.write("\n")
        holder.stdin.close()
        holder.wait(timeout=10)
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


# --- where the reference data came from (SPEC "Storage": the sources table) --------------

CMS_SOURCE = {"name": "CMS Hospital General Information", "url": "https://data.cms.gov/x.csv",
              "release_date": "2026-07-22", "sha256": "a" * 64, "size_bytes": 1234, "note": "Hospital General Information"}
ZCTA_SOURCE = {"name": "Census ZCTA gazetteer", "url": "https://www2.census.gov/z.zip",
               "release_date": "2024", "sha256": "b" * 64, "size_bytes": 99}


def test_the_build_records_where_each_dataset_came_from(tmp_path):
    from hpa import store

    db = tmp_path / "hpa.duckdb"
    result = build_database(db, str(FIXTURES / "hospitals.csv"), str(FIXTURES / "zcta.txt"),
                            str(FIXTURES / "coords.csv"), [CMS_SOURCE, ZCTA_SOURCE], **SMALL)
    recorded = {s["name"]: s for s in store.sources(duckdb.connect(str(db), read_only=True))}

    assert set(recorded) == {"CMS Hospital General Information", "Census ZCTA gazetteer"}
    cms = recorded["CMS Hospital General Information"]
    assert cms["release_date"] == "2026-07-22" and cms["sha256"] == "a" * 64
    # The row count is the number actually loaded, not one typed anywhere.
    assert cms["rows"] == result["hospitals"]
    assert recorded["Census ZCTA gazetteer"]["rows"] == result["zips"]


def test_a_rebuild_keeps_the_provenance_of_what_came_before(tmp_path):
    from hpa import store

    db = tmp_path / "hpa.duckdb"
    build_database(db, str(FIXTURES / "hospitals.csv"), str(FIXTURES / "zcta.txt"), None, [CMS_SOURCE], **SMALL)
    build_database(db, str(FIXTURES / "hospitals.csv"), str(FIXTURES / "zcta.txt"), None,
                   [{**CMS_SOURCE, "release_date": "2026-08-19", "sha256": "c" * 64}], **SMALL)

    con = duckdb.connect(str(db), read_only=True)
    every = con.execute("SELECT release_date FROM sources ORDER BY fetched_at").fetchall()
    assert [r[0] for r in every] == ["2026-07-22", "2026-08-19"]  # history, not a replacement
    assert store.sources(con)[0]["release_date"] == "2026-08-19"  # newest per dataset


def test_a_database_built_before_provenance_existed_still_reads(tmp_path):
    from hpa import store

    db = tmp_path / "old.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE sources (name VARCHAR, url VARCHAR, fetched_at TIMESTAMP, note VARCHAR)")
    con.execute("INSERT INTO sources VALUES ('CMS Hospital General Information', 'https://x', now(), 'old row')")
    con.close()

    old = store.sources(duckdb.connect(str(db), read_only=True))
    assert old[0]["note"] == "old row" and old[0]["release_date"] is None

    store.connect(db).close()  # opening for writing migrates it
    migrated = store.sources(duckdb.connect(str(db), read_only=True))
    assert migrated[0]["note"] == "old row" and "release_date" in migrated[0]
