"""Command line entry point: `hpa setup`, `hpa hospitals ZIP`, `hpa catalog [QUERY]`."""

import argparse
import sys
from pathlib import Path

from hpa import catalog, reference, store
from hpa.geo import KM_PER_MILE, load_zcta
from hpa.hospitals import UnknownZip, find_hospitals, load_hospitals, location_counts


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

    # Rebuild from scratch so tables from older versions never linger.
    db = Path(args.db)
    if db.exists():
        db.unlink()
    con = store.connect(db)
    print(f"loaded {load_zcta(con, str(zcta_txt)):,} ZIP centroids")
    print(f"loaded {load_hospitals(con, str(hgi_csv), coords_csv and str(coords_csv)):,} hospitals")
    counts = location_counts(con)
    rejected = con.execute("SELECT count(*) FROM hospitals WHERE location_note IS NOT NULL").fetchone()[0]
    print(
        f"located {counts['address']:,} by street address, {counts['zip']:,} by ZIP centroid "
        f"({rejected} geocodes rejected as too far from their ZIP); "
        f"{counts['unresolved']} unresolved (excluded from results)"
    )
    return 0


def cmd_hospitals(args: argparse.Namespace) -> int:
    if not Path(args.db).exists():
        print("no hospital data yet; run `hpa setup` first", file=sys.stderr)
        return 1
    con = store.connect(args.db, read_only=True)
    try:
        found = find_hospitals(con, args.zip, args.limit, include_federal=args.include_federal)
    except UnknownZip as e:
        print(e, file=sys.stderr)
        return 1
    print(f"nearest {len(found)} hospitals to the centre of {args.zip}")
    for h in found:
        miles = h.distance_km / KM_PER_MILE
        shown = f"<= {miles:.1f} mi" if h.distance_is_bound else f"{miles:>7.1f} mi"
        note = "  (ZIP centroid)" if h.distance_is_bound else ""
        print(f"  {shown:>10}  {h.name}  [{h.ccn}, {h.hospital_type}]{note}")
    return 0


def cmd_catalog(args: argparse.Namespace) -> int:
    services = catalog.load()
    reviewed = sum(s.reviewed for s in services)
    if not args.query:
        print(f"{len(services)} services ({reviewed} of {len(services)} mapping-reviewed)")
        for s in services:
            print(f"  {s.code_list:<18} {s.name}  [{'reviewed' if s.reviewed else 'unreviewed'}]")
        return 0

    r = catalog.resolve(args.query, services)
    if r.verdict == catalog.SELECTED:
        s = r.service
        print(f"{r.verdict}: {s.name} ({s.code_list})  [{'reviewed' if s.reviewed else 'unreviewed'}]")
        if s.notes:
            print(f"  note: {s.notes}")
        others = [c for c in r.candidates if c is not s]
        if others:
            print("  other candidates: " + "; ".join(f"{c.name} ({c.code_list})" for c in others))
        return 0
    print(f"{r.verdict}: {r.reason}")
    for c in r.candidates:
        print(f"  {c.code_list:<18} {c.name}")
    return 1


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
    p.add_argument("--include-federal", action="store_true", help="include VA and DoD hospitals, which are exempt from the rule")

    p = sub.add_parser("catalog", help="list the 70 CMS shoppable services, or resolve a query to one")
    p.add_argument("query", nargs="?", help='e.g. "knee mri" or a code like 45378')

    args = parser.parse_args(argv)
    return {"setup": cmd_setup, "hospitals": cmd_hospitals, "catalog": cmd_catalog}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
