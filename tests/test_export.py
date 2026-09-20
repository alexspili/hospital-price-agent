"""The compact copy that seeds the hosted demo."""

from pathlib import Path

import pytest

from hpa import export, mrf, store
from hpa.geo import load_zcta
from hpa.hospitals import load_hospitals

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://example.test/f.csv"


@pytest.fixture
def con():
    con = store.connect(":memory:")
    load_zcta(con, str(FIXTURES / "zcta.txt"))
    load_hospitals(con, str(FIXTURES / "hospitals.csv"), str(FIXTURES / "coords.csv"))
    # One scanned hospital near 77030, and one scanned hospital far away that the demo
    # ZIPs do not reach: the far one must not travel.
    for ccn, url in (("450289", URL), ("670122", "https://example.test/far.csv")):
        con.execute("INSERT INTO hospital_files VALUES (?, 'H', now(), true, 'cms-hpt', 'example.test', NULL, NULL, NULL, ?, 'csv-wide', 10, NULL, NULL, NULL, '', '[]', 1.0)", [ccn, url])
        con.execute("INSERT INTO fetches VALUES (?, now(), 200, ?, 'text/csv', NULL, NULL, 10, ?, 1.0, '')", [url, url, f"sum{ccn}"])
        con.execute("INSERT OR REPLACE INTO files VALUES (?, 'csv-wide', '3.0.0', 'H', '2026-09-01', '', 10, now())", [f"sum{ccn}"])
        con.execute("INSERT INTO extractions VALUES (?, ?, ?, now(), 1, 1, 1.0, 1.0, true, '')", [f"ext{ccn}", f"sum{ccn}", mrf.PARSER_VERSION])
        con.execute("INSERT INTO items VALUES (?, 'i1', 'MRI', NULL, NULL)", [f"ext{ccn}"])
        con.execute("INSERT INTO item_codes VALUES (?, 'i1', 'CPT', '73721')", [f"ext{ccn}"])
        con.execute("INSERT INTO charges VALUES (?, 'c1', 'i1', 'outpatient', 'facility', NULL, 1.0, 2.0, 3.0, 4.0, NULL, 'row 1', NULL)", [f"ext{ccn}"])
    con.execute("INSERT INTO llm_cache VALUES ('k', 'claude-opus-5', '1', '{}', '{}', now())")
    return con


def test_it_carries_the_pre_scanned_zips_and_leaves_the_rest(con, tmp_path):
    out = tmp_path / "demo.duckdb"
    counts = export.export_demo(con, out, ["77030"])

    # The reference tables travel whole, so any ZIP still works on the copy.
    assert counts["hospitals"] == con.execute("SELECT count(*) FROM hospitals").fetchone()[0]
    assert counts["zcta"] == con.execute("SELECT count(*) FROM zcta").fetchone()[0]
    assert counts["extractions"] == 1 and counts["charges"] == 1
    assert counts["llm_cache"] == 1  # answers already paid for

    copy = store.connect(out, read_only=True)
    assert [r[0] for r in copy.execute("SELECT ccn FROM hospital_files").fetchall()] == ["450289"]
    assert copy.execute("SELECT count(*) FROM charges WHERE extraction_id = 'ext670122'").fetchone()[0] == 0
    copy.close()


def test_the_copy_reopens_as_a_working_store(con, tmp_path):
    out = tmp_path / "demo.duckdb"
    export.export_demo(con, out, ["77030"])
    hospitals = con.execute("SELECT count(*) FROM hospitals").fetchone()[0]
    assert export.verify(out) == {"hospitals": hospitals, "located": 1, "extractions": 1, "charges": 1}


def test_exporting_twice_replaces_the_file(con, tmp_path):
    out = tmp_path / "demo.duckdb"
    export.export_demo(con, out, ["77030"])
    again = export.export_demo(con, out, ["77030"])
    assert again["charges"] == 1  # not doubled, and no "table already exists"


def test_the_copy_keeps_the_keys_a_scan_relies_on(con, tmp_path):
    """A CREATE TABLE AS copy has no primary keys, and the first scan on it died at
    `files`. The copy is made from the schema, so a hosted live scan can store a file."""
    out = tmp_path / "demo.duckdb"
    export.export_demo(con, out)
    copy = store.connect(out)  # read-write, as the server opens it
    keyed = {r[0] for r in copy.execute(
        "SELECT DISTINCT table_name FROM duckdb_constraints() WHERE constraint_type = 'PRIMARY KEY'").fetchall()}
    assert keyed >= set(store.KEYED_TABLES)
    copy.execute("INSERT OR REPLACE INTO files VALUES ('sum1', 'csv-wide', '3.0.0', 'X', '2026-01-01', '', 1, now())")
    copy.execute("INSERT OR REPLACE INTO files VALUES ('sum1', 'csv-wide', '3.0.0', 'Y', '2026-01-01', '', 1, now())")
    assert copy.execute("SELECT hospital_name FROM files WHERE checksum = 'sum1'").fetchall() == [("Y",)]
    copy.close()


def test_a_store_that_lost_its_keys_gets_them_back(tmp_path):
    path = tmp_path / "old.duckdb"
    con = store.connect(path)
    con.execute("INSERT INTO llm_cache VALUES ('k', 'm', '1', 'in', 'out', now())")
    # What an older export or rebuild left behind: the same rows, no key, a duplicate.
    con.execute("CREATE TABLE keyless AS SELECT * FROM llm_cache")
    con.execute("INSERT INTO keyless SELECT * FROM llm_cache")
    con.execute("DROP TABLE llm_cache")
    con.execute("ALTER TABLE keyless RENAME TO llm_cache")
    con.close()
    con = store.connect(path)  # migrate() restores the key and drops the duplicate
    assert con.execute("SELECT count(*) FROM llm_cache").fetchone()[0] == 1
    con.execute("INSERT OR REPLACE INTO llm_cache VALUES ('k', 'm', '1', 'in', 'out2', now())")
    assert con.execute("SELECT output FROM llm_cache").fetchone() == ("out2",)
