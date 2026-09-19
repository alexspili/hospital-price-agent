"""Command line entry point: `hpa setup`, `hpa hospitals ZIP`, `hpa catalog [QUERY]`, `hpa locate ZIP`."""

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from hpa import build, catalog, discovery, geocode, llm, reference, store
from hpa.geo import KM_PER_MILE
from hpa.hospitals import UnknownZip, find_hospitals


def cmd_setup(args: argparse.Namespace) -> int:
    try:
        with build.setup_lock(Path(args.db)):
            return _setup(args)
    except build.SetupInProgress as e:
        print(e, file=sys.stderr)
        return 1


def _setup(args: argparse.Namespace) -> int:
    with reference.client() as client:
        print("downloading CMS Hospital General Information and Census ZCTA gazetteer")
        hgi_csv = reference.fetch_cms_hospitals(client)
        zcta_txt = reference.fetch_zcta_gazetteer(client)
        coords_csv = None
        if not args.skip_geocoding:
            print("geocoding hospital street addresses with the Census Geocoder (about a minute)")
            try:
                coords_csv, matched = reference.geocode_hospitals(client, hgi_csv)
            except (geocode.GeocodeError, httpx.HTTPError) as e:
                print(f"geocoding failed: {e}\nrerun later, or use --skip-geocoding for ZIP centroids only", file=sys.stderr)
                return 1
            print(f"geocoded {matched:,} addresses")

    # Built in a temporary file and swapped in only if it checks out, so a bad download
    # never costs you the database you had.
    try:
        r = build.build_database(Path(args.db), str(hgi_csv), str(zcta_txt), coords_csv and str(coords_csv))
    except Exception as e:
        print(f"setup failed, existing database left untouched: {e}", file=sys.stderr)
        return 1
    print(f"loaded {r['zips']:,} ZIP centroids and {r['hospitals']:,} hospitals")
    print(
        f"located {r['address']:,} by street address, {r['zip']:,} by ZIP centroid "
        f"({r['rejected_geocodes']} geocodes rejected as too far from their ZIP); "
        f"{r['unresolved']} unresolved (excluded from results)"
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
        shown = f"~{miles:.1f} mi" if h.approximate else f"{miles:.1f} mi"
        note = "  (ZIP centroid)" if h.approximate else ""
        print(f"  {shown:>9}  {h.name}  [{h.ccn}, {h.hospital_type}]{note}")
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


def cmd_locate(args: argparse.Namespace) -> int:
    if not Path(args.db).exists():
        print("no hospital data yet; run `hpa setup` first", file=sys.stderr)
        return 1
    con = store.connect(args.db)
    hospitals: dict[str, object] = {}
    for z in args.zip:
        try:
            for h in find_hospitals(con, z, args.limit):
                hospitals.setdefault(h.ccn, h)
        except UnknownZip as e:
            print(e, file=sys.stderr)
            return 1
    if args.ccn:
        row = con.execute("SELECT ccn FROM hospitals WHERE ccn = ?", [args.ccn]).fetchone()
        if not row:
            print(f"no hospital with CCN {args.ccn}", file=sys.stderr)
            return 1
        hospitals[args.ccn] = next(h for h in find_hospitals(con, con.execute(
            "SELECT zip FROM hospitals WHERE ccn = ?", [args.ccn]).fetchone()[0], 50, include_federal=True) if h.ccn == args.ccn)
    print(f"locating price files for {len(hospitals)} hospitals")

    claude = None
    if llm.have_api_key() and not args.no_llm:
        # A DuckDB connection is not thread-safe; a cursor is a separate connection the
        # worker threads can use while the main thread writes results.
        claude = llm.Claude(llm.make_client(), con.cursor())
    else:
        print("  (no ANTHROPIC_API_KEY: web-search and tie-break fallbacks disabled)")
    lock = threading.Lock()

    def trace(line: str) -> None:
        with lock:
            print(line, flush=True)

    # One Claude call at a time keeps the trace readable and the cache cursor single-threaded.
    def tie_breaker(h, cands):
        with lock:
            return claude.pick_entry(h, cands)

    def web_search(h):
        with lock:
            return claude.find_hospital_website(h)

    results = []
    todo = []
    for h in hospitals.values():
        cached = None if args.fresh else store.cached_discovery(con, h.ccn)
        if cached:
            trace(f"{discovery.short_name(h)}: cached result from {cached['discovered_at']:%Y-%m-%d}: "
                  + (f"{cached['shape']} file at {cached['domain']}" if cached["ok"] else cached["reason"]))
            results.append(cached)
        else:
            todo.append(h)
    with httpx.Client() as client, ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(discovery.locate_price_file, client, h, trace,
                        tie_breaker if claude else None, web_search if claude else None): h
            for h in todo
        }
        for f in as_completed(futures):
            d = f.result()
            store.save_discovery(con, d)
            results.append(store.cached_discovery(con, d.ccn))

    print()
    ok = sum(1 for r in results if r["ok"])
    print(f"{ok} of {len(results)} hospitals resolved to a probed price file")
    for r in sorted(results, key=lambda r: (not r["ok"], r["name"])):
        status = f"{r['shape']}, {human_size(r['size_bytes'])} via {r['method']}" if r["ok"] else f"FAILED: {r['reason']}"
        print(f"  {r['name']:<45} {status}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1, default=str))
        print(f"wrote {args.json}")
    return 0 if ok == len(results) else 2


def cmd_eval_discovery(args: argparse.Namespace) -> int:
    """Compare located domains with an external, dated index (see scripts/fetch_eval_index.py)."""
    from urllib.parse import urlsplit

    from rapidfuzz import fuzz

    index_path = Path(__file__).resolve().parents[2] / "eval" / "dolthub_hospitals_tx.json"
    index = json.loads(index_path.read_text())
    con = store.connect(args.db, read_only=True)
    ours = con.execute("""
        SELECT ccn, name, ok, domain, mrf_url FROM hospital_files
        QUALIFY row_number() OVER (PARTITION BY ccn ORDER BY discovered_at DESC) = 1
    """).fetchall()

    def dom(url):
        return (urlsplit(url).netloc or "").lower().removeprefix("www.")

    def norm(name):
        return discovery._match_tokens(name)

    print(f"external index: {len(index['rows'])} Texas rows, publish dates 2020-2021, fetched {index['fetched_on']}")
    agree = disagree = 0
    for ccn, name, ok, domain, mrf_url in sorted(ours, key=lambda r: r[1]):
        best = max(index["rows"], key=lambda r: fuzz.token_sort_ratio(norm(name), norm(r["name"])))
        score = fuzz.token_sort_ratio(norm(name), norm(best["name"]))
        if score < 85:
            continue
        theirs, mine = dom(best["url"]), (dom(mrf_url) if ok and mrf_url else None)
        same = mine is not None and (mine == theirs or mine.endswith("." + theirs) or theirs.endswith("." + mine))
        agree += same
        disagree += not same
        print(f"  {name:<40} index: {theirs:<28} ours: {mine or 'FAILED':<40} {'agree' if same else 'DIFFER'}")
    print(f"{agree} agree, {disagree} differ, {len(ours) - agree - disagree} of ours not in the index")
    return 0


def human_size(n: int | None) -> str:
    if n is None:
        return "size unknown"
    if n < 1_000_000:
        return f"{n / 1e3:,.0f} KB"
    return f"{n / 1e6:,.0f} MB"


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

    p = sub.add_parser("locate", help="find the price transparency file for the hospitals nearest ZIP codes")
    p.add_argument("zip", nargs="*", help="one or more ZIP codes")
    p.add_argument("--ccn", help="a single hospital by CMS certification number")
    p.add_argument("--limit", type=positive_int, default=5, help="hospitals per ZIP (default 5)")
    p.add_argument("--fresh", action="store_true", help="ignore cached discovery results")
    p.add_argument("--no-llm", action="store_true", help="never call Claude, even if a key is set")
    p.add_argument("--json", help="also write the results to this file")

    sub.add_parser("eval-discovery", help="compare located file domains with the external index in eval/")

    args = parser.parse_args(argv)
    return {"setup": cmd_setup, "hospitals": cmd_hospitals, "catalog": cmd_catalog, "locate": cmd_locate,
            "eval-discovery": cmd_eval_discovery}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
