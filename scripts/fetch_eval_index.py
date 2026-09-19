"""Snapshot the DoltHub hospital-price-transparency `hospitals` table for Texas.

An external, dated list of hospital → price-file URLs, used as the oracle for the
discovery accuracy number in docs/houston-compliance-findings.md. It is keyed by NPI (not
CCN) and its URLs date from 2020–2021, so agreement is measured on the *domain*, not the
URL, and the snapshot's age is reported alongside the number.
"""

import json
import sys
from datetime import date
from pathlib import Path

import httpx

API = "https://www.dolthub.com/api/v1alpha1/dolthub/hospital-price-transparency/master"
QUERY = "SELECT npi_number, name, url, street_address, city, state, zip_code, publish_date FROM hospitals WHERE state = 'TX'"


def main() -> int:
    resp = httpx.get(API, params={"q": QUERY}, timeout=60).raise_for_status().json()
    if resp.get("query_execution_status") != "Success":
        print(resp.get("query_execution_message"), file=sys.stderr)
        return 1
    out = {"source": API, "query": QUERY, "fetched_on": date.today().isoformat(), "rows": resp["rows"]}
    dest = Path(__file__).resolve().parents[1] / "eval" / "dolthub_hospitals_tx.json"
    dest.write_text(json.dumps(out, indent=1))
    print(f"{len(resp['rows'])} Texas rows -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
