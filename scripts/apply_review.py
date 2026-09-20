"""Read the answers in docs/mapping-review.csv into src/hpa/data/shoppable_services.json.

A service becomes `reviewed` when its alias_means_this_service answer is "yes" on at least
one row; the entry records reviewer, date, per-hospital confirmations and notes, so the
review is evidence, not a flag. "no" or "needs qualifier" answers are kept as notes and do
not mark it reviewed.
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_IN = ROOT / "docs" / "mapping-review.csv"
CATALOG = ROOT / "src" / "hpa" / "data" / "shoppable_services.json"


def main(csv_in: Path = CSV_IN, catalog_path: Path = CATALOG) -> int:
    with open(csv_in, newline="") as f:
        rows = list(csv.DictReader(f))
    by_service = defaultdict(list)
    for r in rows:
        if any(r.get(k, "").strip() for k in ("alias_means_this_service", "headline_is_this_service", "note")):
            by_service[r["service_id"]].append(r)
    data = json.loads(catalog_path.read_text())
    changed = 0
    for svc in data["services"]:
        answers = by_service.get(svc["id"])
        if not answers:
            continue
        alias_yes = [a for a in answers if a["alias_means_this_service"].strip().lower() == "yes"]
        review = {
            "reviewer": next((a["reviewer"] for a in answers if a.get("reviewer")), ""),
            "date": next((a["date"] for a in answers if a.get("date")), ""),
            "alias_confirmed": bool(alias_yes),
            "hospitals": [
                # The ref and the description together are the evidence reviewed: a
                # reordered file moves the ref, and the review must not move with it.
                {"hospital": a["hospital"], "headline_is_this_service": a["headline_is_this_service"].strip().lower() or None,
                 "billing_class": a["billing_class_if_known"].strip() or None, "note": a["note"].strip() or None,
                 "ref": a["ref"], "description": a.get("headline_description", "").strip() or None}
                for a in answers
            ],
        }
        svc["reviewed"] = review if alias_yes else False
        if not alias_yes:
            svc["notes"] = (svc["notes"] + " " if svc["notes"] else "") + "Review: alias not confirmed: " + "; ".join(
                f"{a['hospital']}: {a['alias_means_this_service'] or a['note']}" for a in answers)
        changed += 1
    catalog_path.write_text(json.dumps(data, indent=1))
    reviewed = sum(1 for s in data["services"] if s["reviewed"])
    print(f"{changed} services updated from {len(rows)} rows; {reviewed} of {len(data['services'])} now reviewed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
