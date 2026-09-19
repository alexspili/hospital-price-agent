"""Command line entry point: `hpa setup`, `hpa hospitals ZIP`, `hpa catalog [QUERY]`."""

import argparse
import sys

from hpa import catalog, reference, store
from hpa.geo import KM_PER_MILE, load_zcta
from hpa.hospitals import (
    DEFAULT_TYPES,
    UnknownZip,
    find_hospitals,
    load_hospitals,
    location_counts,
)


def cmd_setup(args: argparse.Namespace) -> int:
    with reference.client() as client:
        print("downloading CMS Hospital General Information and Census ZCTA gazetteer")
        hgi_csv = reference.fetch_cms_hospitals(client)
        zcta_txt = reference.fetch_zcta_gazetteer(client)
        coords_csv = None
        if not args.skip_geocoding:
            print("geocoding hospital street addresses with the Census Geocoder (about a minute)")
            coords_csv, matched = reference.geocode_hospitals(client, hgi_csv)
            print(f"geocoded {matched:,} addresses")

    con = store.connect(args.db)
    print(f"loaded {load_zcta(con, str(zcta_txt)):,} ZIP centroids")
    print(f"loaded {load_hospitals(con, str(hgi_csv), coords_csv and str(coords_csv)):,} hospitals")
    counts = location_counts(con)
    print(
        f"located {counts['address']:,} by street address, {counts['zip']:,} by ZIP centroid; "
        f"{counts['unresolved']} unresolved (excluded from results)"
    )
    return 0


def cmd_hospitals(args: argparse.Namespace) -> int:
    con = store.connect(args.db)
    if not con.execute("SELECT 1 FROM duckdb_tables() WHERE table_name = 'hospitals'").fetchone():
        print("no hospital data yet; run `hpa setup` first", file=sys.stderr)
        return 1
    try:
        types = None if args.all_types else DEFAULT_TYPES
        found = find_hospitals(con, args.zip, args.limit, types=types)
    except UnknownZip as e:
        print(e, file=sys.stderr)
        return 1
    print(f"nearest {len(found)} hospitals to {args.zip}")
    for h in found:
        note = "  (ZIP centroid)" if h.location_source == "zip" else ""
        miles = h.distance_km / KM_PER_MILE
        print(f"  {miles:>5.1f} mi  {h.name}  [{h.ccn}, {h.hospital_type}]{note}")
    return 0


def cmd_catalog(args: argparse.Namespace) -> int:
    services = catalog.load()
    if args.query:
        services = catalog.search(args.query, services)
        if not services:
            print(f"nothing in the catalog matches {args.query!r}", file=sys.stderr)
            return 1
    verified = sum(s.verified for s in catalog.load())
    print(f"{len(services)} services ({verified} of 70 hand-verified)")
    for s in services:
        flag = "verified" if s.verified else "unverified"
        print(f"  {s.code_list:<18} {s.name}  [{flag}]")
    return 0


def positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hpa", description=__doc__)
    parser.add_argument("--db", default=store.DEFAULT_DB, help="DuckDB file (default: data/hpa.duckdb)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="download reference data and build the local database")
    p.add_argument("--skip-geocoding", action="store_true", help="use ZIP centroids only (faster, coarser)")

    p = sub.add_parser("hospitals", help="list the hospitals nearest a ZIP code")
    p.add_argument("zip")
    p.add_argument("--limit", type=positive_int, default=5, help="how many hospitals (default 5)")
    p.add_argument("--all-types", action="store_true", help="include psychiatric, federal, long-term")

    p = sub.add_parser("catalog", help="list or search the 70 CMS shoppable services")
    p.add_argument("query", nargs="?", help='e.g. "knee mri" or a code like 45378')

    args = parser.parse_args(argv)
    return {"setup": cmd_setup, "hospitals": cmd_hospitals, "catalog": cmd_catalog}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
