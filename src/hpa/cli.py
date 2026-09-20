"""Command line entry point: `hpa setup`, `hpa hospitals ZIP`, `hpa catalog [QUERY]`, `hpa locate ZIP`."""

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb
import httpx

from hpa import build, catalog, client, demo, discovery, evaluate, export, geocode, llm, pipeline, reference, scan, store, targets
from hpa.geo import KM_PER_MILE
from hpa.hospitals import UnknownZip, find_hospitals, hospital_by_ccn


class DatabaseBusy(RuntimeError):
    """Someone else holds the database file. Says who, and what to do about it."""


def open_db(args: argparse.Namespace, read_only: bool = False):
    """The store, or a clear reason why not.

    While `hpa serve` runs it owns the file and no other process can open it, even
    read-only (SPEC "Process model"), so commands that need the file say so plainly
    instead of failing with a DuckDB lock error.
    """
    url = client.running_server()
    if url:
        raise DatabaseBusy(f"the server at {url} owns the database; stop it, or use the web page")
    try:
        return store.connect(args.db, read_only=read_only)
    except duckdb.IOException as e:
        raise DatabaseBusy(f"{args.db} is open in another process; stop it and try again ({e})") from None


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
    con = open_db(args, read_only=True)
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
    reviewed = sum(1 for s in services if s.reviewed)
    if not args.query:
        print(f"{len(services)} services ({reviewed} of {len(services)} mapping-reviewed)")
        for s in services:
            print(f"  {s.code_list:<18} {s.name}  [{'reviewed' if s.reviewed else 'unreviewed'}]")
        return 0

    r = catalog.resolve(args.query, services)
    for typed, known in r.corrections:
        print(f'read "{typed}" as "{known}"')
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
    con = open_db(args)
    hospitals: dict[str, object] = {}
    for z in args.zip:
        try:
            for h in find_hospitals(con, z, args.limit):
                hospitals.setdefault(h.ccn, h)
        except UnknownZip as e:
            print(e, file=sys.stderr)
            return 1
    if args.ccn:
        h = hospital_by_ccn(con, args.ccn)
        if h is None:
            print(f"no hospital with CCN {args.ccn}", file=sys.stderr)
            return 1
        hospitals[args.ccn] = h
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


def cmd_scan(args: argparse.Namespace) -> int:
    if not Path(args.db).exists():
        print("no hospital data yet; run `hpa setup` first", file=sys.stderr)
        return 1
    con = open_db(args)
    try:
        pairs = targets.located(con, args.zip, args.ccn, args.limit)
    except UnknownZip as e:
        print(e, file=sys.stderr)
        return 1
    todo = [(h, c) for h, c in pairs if c and c["ok"]]
    skipped = [(h, c) for h, c in pairs if not (c and c["ok"])]
    for h, c in skipped:
        print(f"{discovery.short_name(h)}: no located file ({c['reason'] if c else 'run `hpa locate` first'}) — skipped")
    print(f"scanning {len(todo)} price files")
    results = []
    with httpx.Client() as client:
        for h, c in todo:
            who = discovery.short_name(h)
            r = scan.scan(con, client, h.ccn, c["mrf_url"], lambda line, who=who: print(f"{who}: {line}", flush=True), force=args.force)
            results.append((h, r))
    print()
    ok = [r for _, r in results if r.ok]
    print(f"{len(ok)} of {len(results)} files extracted")
    print(f"  {'hospital':<42} {'size':>8} {'charges':>9} {'items':>8} {'download':>9} {'total':>7} {'peak RSS':>9}")
    for h, r in sorted(results, key=lambda x: (not x[1].ok, x[0].name)):
        if r.ok:
            print(f"  {h.name[:42]:<42} {scan._fmt_size(r.size_bytes):>8} {r.charges:>9,} {r.items:>8,} {r.download_seconds:>8.0f}s {r.seconds:>6.0f}s {r.peak_rss_mb:>7.0f} MB" + ("  (cached)" if r.cached else ""))
        else:
            print(f"  {h.name[:42]:<42} FAILED: {r.reason}")
    return 0 if len(ok) == len(results) else 2


def cmd_prices(args: argparse.Namespace) -> int:
    """Read-only, so it keeps working while the server holds the database: the answer
    then comes from the server's API instead of the file (SPEC "Process model")."""
    shown = None if args.all else pipeline.SHOWN_LINES
    url = client.running_server()
    if url:
        try:
            payload = client.get_prices(url, args.service, args.zip, args.ccn, args.limit, args.all)
        except (httpx.HTTPError, RuntimeError) as e:
            print(e, file=sys.stderr)
            return 1
    else:
        con = open_db(args, read_only=True)
        try:
            payload = pipeline.prices_payload(con, args.service, args.zip, args.ccn, args.limit,
                                              shown_lines=shown, use_llm=not args.no_llm)
        except UnknownZip as e:
            print(e, file=sys.stderr)
            return 1
    return print_prices(payload, args.all)


def money(v) -> str:
    return f"${v:,.2f}" if v is not None else "—"


def print_prices(payload: dict, show_all: bool) -> int:
    for typed, known in payload.get("corrections") or []:
        print(f'read "{typed}" as "{known}"')
    if payload.get("resolver"):
        print(f"resolver: {payload['resolver']['verdict']}: {payload['resolver']['reason']}")
    note = payload.get("note")
    if payload["status"] != "ok":
        if note is not None:
            print(f"claude: asks: {note}")
        for c in payload["candidates"]:
            print(f"  {c['codes']:<18} {c['name']}")
        return 1
    s = payload["service"]
    if note is not None:
        print(f"claude: picked {s['name']} ({note})")
    print(f"{s['name']} ({s['codes']})  [{'reviewed' if s['reviewed'] else 'unreviewed'}]")
    for h in payload["hospitals"]:
        print_hospital(h, show_all)
    return 0


def print_hospital(h: dict, show_all: bool) -> None:
    if h["verdict"] == pipeline.NO_FILE:
        print(f"\n{h['name']}: no price file located")
        return
    if h["verdict"] == pipeline.NOT_SCANNED:
        print(f"\n{h['name']}: file located but not scanned yet (hpa scan)")
        return
    print(f"\n{h['name']}  (file dated {h['file_date'] or '?'}; {(h['url'] or '')[:60]}…)")
    print(f"  verdict: {h['verdict']}" + (f" — {h['detail']}" if h["detail"] else ""))
    hl = h["headline"]
    if hl:
        print(f"  cash {money(hl['cash'])}  gross {money(hl['gross'])}  negotiated {money(hl['min'])}–{money(hl['max'])}  [{hl['context']}]  {hl['ref']}")
        print(f"      {hl['description'][:100]}")
    if show_all or not hl:
        for l in h["lines"]:
            extra = f" + {', '.join(l['other_codes'])}" if l["other_codes"] else ""
            print(f"    {l['code_type']} {l['code']}{extra}  cash {money(l['cash'])}  gross {money(l['gross'])}  negotiated {money(l['min'])}–{money(l['max'])}  [{l['context']}]  {l['ref']}"
                  + (f"  note: {l['note']}" if l["note"] else ""))
        hidden = h["line_count"] - len(h["lines"])
        if hidden > 0:
            print(f"    … {hidden} more lines (--all)")


def cmd_export_demo(args: argparse.Namespace) -> int:
    """The compact database the hosted demo runs on (SPEC "Hosted demo constraints")."""
    con = open_db(args, read_only=True)
    try:
        counts = export.export_demo(con, args.out, args.zip or demo.DEFAULT_ZIPS, args.limit)
    except UnknownZip as e:
        print(e, file=sys.stderr)
        return 1
    print(f"wrote {args.out} ({counts['bytes'] / 1e6:,.0f} MB) for {counts['hospitals_kept']} hospitals "
          f"near {', '.join(args.zip or demo.DEFAULT_ZIPS)}")
    print(f"  {counts['extractions']:,} extractions, {counts['charges']:,} charges, "
          f"{counts['items']:,} items, {counts['llm_cache']:,} cached model answers")
    found = export.verify(args.out)
    print(f"  reopened read-only: {found['located']} located files, {found['extractions']} extractions, "
          f"{found['charges']:,} charges")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """The web page and the API. This process then owns the database file."""
    url = client.running_server()
    if url:
        print(f"a server is already running at {url}", file=sys.stderr)
        return 1
    from hpa import server  # imported here so the rest of the CLI does not need FastAPI

    return server.serve(args.db, args.host, args.port, args.url)


def cmd_eval_discovery(args: argparse.Namespace) -> int:
    """Compare located domains with an external, dated index (see scripts/fetch_eval_index.py)."""
    from urllib.parse import urlsplit

    from rapidfuzz import fuzz

    index_path = Path(__file__).resolve().parents[2] / "eval" / "dolthub_hospitals_tx.json"
    index = json.loads(index_path.read_text())
    con = open_db(args, read_only=True)
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


def cmd_demo(args: argparse.Namespace) -> int:
    if args.record:
        con = open_db(args, read_only=True)
        data = demo.record(con)
        demo.DEMO_FILE.parent.mkdir(exist_ok=True)
        demo.DEMO_FILE.write_text(json.dumps(data, indent=1, default=float))
        print(f"recorded {sum(len(v) for v in data['zips'].values())} hospitals and {len(data['services'])} services to {demo.DEMO_FILE}")
        return 0
    if not demo.DEMO_FILE.exists():
        print("no recorded run; use `hpa demo --record` with a scanned database", file=sys.stderr)
        return 1
    demo.replay(json.loads(demo.DEMO_FILE.read_text()), delay=args.delay)
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    con = open_db(args, read_only=True)
    report = evaluate.run(con, sample=args.sample)
    evaluate.print_report(report)
    evaluate.RESULTS.write_text(json.dumps(report, indent=1, default=str))
    print(f"\nwrote {evaluate.RESULTS}")
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

    p = sub.add_parser("scan", help="download and extract the located price files for hospitals near ZIP codes")
    p.add_argument("zip", nargs="*")
    p.add_argument("--ccn")
    p.add_argument("--limit", type=positive_int, default=5)
    p.add_argument("--force", action="store_true", help="re-download and re-extract even if unchanged")

    p = sub.add_parser("prices", help="show the four summary prices for a catalog service at nearby hospitals")
    p.add_argument("service", help='e.g. "knee mri" or 45378')
    p.add_argument("zip", nargs="*")
    p.add_argument("--ccn")
    p.add_argument("--limit", type=positive_int, default=5)
    p.add_argument("--all", action="store_true", help="list every matching line, not just the headline")
    p.add_argument("--no-llm", action="store_true", help="never ask Claude to settle an unclear service name")

    p = sub.add_parser("demo", help="replay the recorded Houston run offline (or --record it from the local database)")
    p.add_argument("--record", action="store_true")
    p.add_argument("--delay", type=float, default=0.0, help="seconds between trace lines when replaying")

    p = sub.add_parser("eval", help="the four accuracy numbers, computed from the local database and the raw files")
    p.add_argument("--sample", type=int, default=25, help="charges re-read from each raw file")

    p = sub.add_parser("serve", help="the web page and its API; this process then owns the database")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--url", help="the address to announce to the CLI (behind a proxy, the public one)")

    p = sub.add_parser("export-demo", help="a compact copy of the store for the hosted demo")
    p.add_argument("--out", default="data/demo.duckdb")
    p.add_argument("zip", nargs="*", help=f"pre-scanned ZIPs (default {', '.join(demo.DEFAULT_ZIPS)})")
    p.add_argument("--limit", type=positive_int, default=5, help="hospitals per ZIP (default 5)")

    args = parser.parse_args(argv)
    commands = {"setup": cmd_setup, "hospitals": cmd_hospitals, "catalog": cmd_catalog, "locate": cmd_locate,
                "eval-discovery": cmd_eval_discovery, "scan": cmd_scan, "prices": cmd_prices,
                "demo": cmd_demo, "eval": cmd_eval, "serve": cmd_serve, "export-demo": cmd_export_demo}
    try:
        return commands[args.command](args)
    except DatabaseBusy as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
