"""A compact copy of the store holding only what the hosted demo answers from.

The working database carries every file ever scanned. The host needs the reference
tables, the discovery results for the pre-scanned ZIPs, and the rows extracted from those
hospitals' files — nothing else. `hpa export-demo` writes that, and it is the thing you
copy onto the server's disk (SPEC "Hosted demo constraints").

The model cache travels too: those answers are already paid for, and carrying them means
the hosted copy resolves the same hospitals the same way without spending anything.
"""

from pathlib import Path

from hpa import demo, store
from hpa.hospitals import find_hospitals

# Copied whole: they are small, and the page's live option needs any ZIP to work.
REFERENCE = ("zcta", "hospitals", "sources")


def demo_hospitals(con, zips, limit: int = 5) -> list[str]:
    """The CCNs the hosted demo can answer for without touching the network."""
    ccns: list[str] = []
    for zip_code in zips:
        for h in find_hospitals(con, zip_code, limit):
            if h.ccn not in ccns:
                ccns.append(h.ccn)
    return ccns


def export_demo(con, out: Path | str, zips=demo.DEFAULT_ZIPS, limit: int = 5) -> dict:
    """Write the compact copy. Returns the row counts, for the trace and the tests."""
    out = Path(out)
    if out.exists():
        out.unlink()  # ATTACH would open it instead of replacing it
    ccns = demo_hospitals(con, zips, limit)

    # ATTACH takes no parameters, so the path is inlined; doubling quotes keeps a path
    # with an apostrophe in it from ending the literal.
    con.execute(f"""ATTACH '{str(out).replace("'", "''")}' AS export""")
    try:
        for table in REFERENCE:
            con.execute(f"CREATE TABLE export.{table} AS SELECT * FROM {table}")
        con.execute("CREATE TABLE export.hospital_files AS SELECT * FROM hospital_files WHERE list_contains(?, ccn)", [ccns])
        con.execute("CREATE TABLE export.llm_cache AS SELECT * FROM llm_cache")
        con.execute("CREATE TABLE export.llm_spend AS SELECT * FROM llm_spend WHERE false")

        # The chain from a located file to its rows: url -> checksum -> extraction.
        con.execute("""
            CREATE TABLE export.fetches AS SELECT * FROM fetches
             WHERE url IN (SELECT mrf_url FROM export.hospital_files WHERE mrf_url IS NOT NULL)
        """)
        con.execute("CREATE TABLE export.files AS SELECT * FROM files WHERE checksum IN (SELECT checksum FROM export.fetches)")
        con.execute("""
            CREATE TABLE export.extractions AS SELECT * FROM extractions
             WHERE checksum IN (SELECT checksum FROM export.fetches WHERE checksum IS NOT NULL)
        """)
        for table in ("items", "item_codes", "charges"):
            con.execute(f"""
                CREATE TABLE export.{table} AS SELECT * FROM {table}
                 WHERE extraction_id IN (SELECT extraction_id FROM export.extractions)
            """)
        counts = {t: con.execute(f"SELECT count(*) FROM export.{t}").fetchone()[0]
                  for t in (*REFERENCE, "hospital_files", "fetches", "files", "extractions",
                            "items", "item_codes", "charges", "llm_cache")}
        con.execute("CHECKPOINT export")
    finally:
        con.execute("DETACH export")

    counts["hospitals_kept"] = len(ccns)
    counts["bytes"] = out.stat().st_size
    return counts


def verify(path: Path | str) -> dict:
    """Open the copy read-only and count what a hosted run would find in it."""
    con = store.connect(path, read_only=True)
    try:
        return {
            "hospitals": con.execute("SELECT count(*) FROM hospitals").fetchone()[0],
            "located": con.execute("SELECT count(*) FROM hospital_files WHERE ok").fetchone()[0],
            "extractions": con.execute("SELECT count(*) FROM extractions WHERE ok").fetchone()[0],
            "charges": con.execute("SELECT count(*) FROM charges").fetchone()[0],
        }
    finally:
        con.close()
