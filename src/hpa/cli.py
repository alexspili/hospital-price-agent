"""Command line entry point: `hpa setup`, `hpa hospitals ZIP`."""

import argparse
import sys

from hpa import reference, store
from hpa.geo import load_zcta
from hpa.hospitals import DEFAULT_TYPES, UnknownZip, find_hospitals, load_hospitals


def cmd_setup(args: argparse.Namespace) -> int:
    print("downloading CMS Hospital General Information and Census ZCTA gazetteer")
    hgi_csv, zcta_txt = reference.fetch_all()
    con = store.connect(args.db)
    print(f"loaded {load_zcta(con, str(zcta_txt)):,} ZIP centroids")
    print(f"loaded {load_hospitals(con, str(hgi_csv)):,} hospitals")
    approx = con.execute("SELECT count(*) FROM hospitals WHERE location_approx").fetchone()[0]
    print(f"{approx} hospitals placed at a nearby ZIP (their own ZIP has no census centroid)")
    return 0


def cmd_hospitals(args: argparse.Namespace) -> int:
    con = store.connect(args.db)
    if not con.execute("SELECT 1 FROM duckdb_tables() WHERE table_name = 'hospitals'").fetchone():
        print("no hospital data yet; run `hpa setup` first", file=sys.stderr)
        return 1
    try:
        types = None if args.all_types else DEFAULT_TYPES
        found = find_hospitals(con, args.zip, args.radius, types=types)
    except UnknownZip as e:
        print(e, file=sys.stderr)
        return 1
    print(f"found {len(found)} hospitals within {args.radius:g} km of {args.zip}")
    for h in found:
        approx = " (approx. location)" if h.location_approx else ""
        print(f"  {h.distance_km:>5.1f} km  {h.name}  [{h.ccn}, {h.hospital_type}]{approx}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hpa", description=__doc__)
    parser.add_argument("--db", default=store.DEFAULT_DB, help="DuckDB file (default: data/hpa.duckdb)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="download reference data and build the local database")

    p = sub.add_parser("hospitals", help="list hospitals near a ZIP code")
    p.add_argument("zip")
    p.add_argument("--radius", type=float, default=25, help="kilometres (default 25)")
    p.add_argument("--all-types", action="store_true", help="include psychiatric, federal, long-term")

    args = parser.parse_args(argv)
    return {"setup": cmd_setup, "hospitals": cmd_hospitals}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
