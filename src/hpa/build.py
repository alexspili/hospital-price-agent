"""Build the reference database safely: into a temporary file, validated, then swapped in."""

import os
from pathlib import Path

from hpa import store
from hpa.geo import load_zcta
from hpa.hospitals import load_hospitals, location_counts


class BuildFailed(RuntimeError):
    pass


def build_database(db: Path, hgi_csv: str, zcta_txt: str, coords_csv: str | None) -> dict:
    """Load everything into `<db>.building`, check it, and rename it over `db`.

    If anything fails, the existing database is left exactly as it was.
    """
    db = Path(db)
    tmp = db.with_name(db.name + ".building")
    if tmp.exists():
        tmp.unlink()
    try:
        con = store.connect(tmp)
        try:
            zips = load_zcta(con, zcta_txt)
            hospitals = load_hospitals(con, hgi_csv, coords_csv)
            counts = location_counts(con)
            if zips < 30_000 or hospitals < 4_000:
                raise BuildFailed(f"implausible row counts: {zips} ZIPs, {hospitals} hospitals")
            if counts["unresolved"] > hospitals * 0.05:
                raise BuildFailed(f"{counts['unresolved']} of {hospitals} hospitals unresolved")
            rejected = con.execute(
                "SELECT count(*) FROM hospitals WHERE location_note IS NOT NULL"
            ).fetchone()[0]
        finally:
            con.close()
        os.replace(tmp, db)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    return {"zips": zips, "hospitals": hospitals, "rejected_geocodes": rejected, **counts}
