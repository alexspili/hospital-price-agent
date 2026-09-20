"""Build the reference database safely: into a temporary file, validated, then swapped in."""

import fcntl
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from hpa import store
from hpa.store import REFERENCE_TABLES
from hpa.geo import load_zcta
from hpa.hospitals import load_hospitals, location_counts


class BuildFailed(RuntimeError):
    pass


class SetupInProgress(RuntimeError):
    pass


@contextmanager
def setup_lock(db: Path) -> Iterator[None]:
    """Exclusive lock for the whole of `hpa setup`, downloads through the final rename,
    so two runs can't trample each other's files."""
    db = Path(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    lock_path = db.with_name(db.name + ".setup.lock")
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupInProgress(f"another `hpa setup` holds {lock_path}") from None
        yield


def _assert_not_held(db: Path) -> None:
    """Refuse to replace a database another process (e.g. the server) has open."""
    if not db.exists():
        return
    try:
        duckdb.connect(str(db)).close()
    except duckdb.IOException as e:
        raise BuildFailed(f"{db} is open in another process; stop it before running setup ({e})")


def build_database(
    db: Path,
    hgi_csv: str,
    zcta_txt: str,
    coords_csv: str | None,
    sources: list[dict] | None = None,
    min_zips: int = 30_000,
    min_hospitals: int = 4_000,
    min_address_share: float = 0.5,
    max_unresolved_share: float = 0.05,
) -> dict:
    """Load everything into a fresh temp file beside `db`, check it, and rename it over `db`.

    If anything fails, the existing database is left exactly as it was. When coordinates
    were supplied, fewer than `min_address_share` of hospitals located by address means
    geocoding went wrong somewhere, which is different from choosing --skip-geocoding.
    """
    db = Path(db)
    _assert_not_held(db)  # before we touch anything; checked again before the rename
    fd, tmp_name = tempfile.mkstemp(prefix=db.name + ".", suffix=".building", dir=db.parent)
    os.close(fd)
    os.unlink(tmp_name)  # DuckDB wants to create the file itself
    tmp = Path(tmp_name)
    try:
        con = store.connect(tmp)
        try:
            zips = load_zcta(con, zcta_txt)
            hospitals = load_hospitals(con, hgi_csv, coords_csv)
            carried = _carry_over(con, db)
            # The carry-over restores the old tables wholesale, including their old shape,
            # so migrate again before writing. Provenance then accumulates rather than
            # being replaced: an earlier build's sources are still there.
            store.migrate(con)
            store.save_sources(con, _with_row_counts(sources or [], zips, hospitals))
            counts = location_counts(con)
            if zips < min_zips or hospitals < min_hospitals:
                raise BuildFailed(f"implausible row counts: {zips} ZIPs, {hospitals} hospitals")
            if counts["unresolved"] > hospitals * max_unresolved_share:
                raise BuildFailed(f"{counts['unresolved']} of {hospitals} hospitals unresolved")
            if coords_csv is not None and counts["address"] < hospitals * min_address_share:
                raise BuildFailed(
                    f"only {counts['address']} of {hospitals} hospitals located by address; "
                    "the geocoding result looks wrong (use --skip-geocoding to build without it)"
                )
            rejected = con.execute(
                "SELECT count(*) FROM hospitals WHERE location_note IS NOT NULL"
            ).fetchone()[0]
        finally:
            con.close()
        _assert_not_held(db)
        os.replace(tmp, db)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
    return {"zips": zips, "hospitals": hospitals, "rejected_geocodes": rejected, "carried_tables": carried, **counts}


def _with_row_counts(sources: list[dict], zips: int, hospitals: int) -> list[dict]:
    """The row count belongs to the dataset that produced it, so the number printed later
    is the number that was actually loaded."""
    rows = {"CMS Hospital General Information": hospitals, "Census ZCTA gazetteer": zips}
    return [{**s, "rows": s.get("rows") or rows.get(s["name"])} for s in sources]


def _carry_over(con, old_db: Path) -> list[str]:
    """Copy every non-reference table (discovery results, caches) from the old database."""
    if not old_db.exists():
        return []
    con.execute(f"ATTACH '{old_db}' AS old (READ_ONLY)")
    try:
        names = [r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = 'old'"
        ).fetchall()]
        carried = []
        known = store.schema_tables()
        for name in names:
            if name in REFERENCE_TABLES:
                continue
            if name in known:
                # The new store already has this table from the schema, keys included;
                # the rows come across, the shape does not.
                con.execute(f'DELETE FROM "{name}"')
                store.copy_table(con, f'"{name}"', f'old."{name}"')
            else:
                con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM old."{name}"')
            carried.append(name)
        return carried
    finally:
        con.execute("DETACH old")
