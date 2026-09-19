import csv
import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location("apply_review", ROOT / "scripts" / "apply_review.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_answers_become_review_evidence(tmp_path):
    catalog = tmp_path / "catalog.json"
    data = json.loads((ROOT / "src" / "hpa" / "data" / "shoppable_services.json").read_text())
    for s in data["services"]:
        s["reviewed"] = False  # start from an unreviewed catalog whatever the real one says
    catalog.write_text(json.dumps(data))
    sheet = tmp_path / "review.csv"
    cols = ["query", "service_id", "service", "codes", "hospital", "ccn", "verdict", "lines", "headline_description",
            "headline_context", "cash", "gross", "min", "max", "ref", "file_date", "url",
            "alias_means_this_service", "headline_is_this_service", "billing_class_if_known", "note", "reviewer", "date"]
    with open(sheet, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        base = {c: "" for c in cols}
        w.writerow({**base, "query": "knee mri", "service_id": "cpt-73721", "hospital": "Houston Methodist Hospital", "ref": "item 13569/charge 1",
                    "alias_means_this_service": "yes", "headline_is_this_service": "yes", "billing_class_if_known": "facility",
                    "reviewer": "A. Reviewer", "date": "2026-09-19"})
        w.writerow({**base, "query": "knee mri", "service_id": "cpt-73721", "hospital": "HCA Houston Healthcare Kingwood", "ref": "",
                    "headline_is_this_service": "unsure", "note": "only RT/LT/50 lines"})
        w.writerow({**base, "query": "colonoscopy", "service_id": "cpt-45378", "hospital": "Harris Health",
                    "alias_means_this_service": "needs qualifier: screening vs diagnostic"})
        w.writerow({**base, "query": "cbc", "service_id": "cpt-85027", "hospital": "Elite Hospital Kingwood"})  # untouched row
    load_script().main(sheet, catalog)
    data = {s["id"]: s for s in json.loads(catalog.read_text())["services"]}
    mri = data["cpt-73721"]["reviewed"]
    assert mri["reviewer"] == "A. Reviewer" and mri["date"] == "2026-09-19" and mri["alias_confirmed"] is True
    assert [h["hospital"] for h in mri["hospitals"]] == ["Houston Methodist Hospital", "HCA Houston Healthcare Kingwood"]
    assert mri["hospitals"][1]["note"] == "only RT/LT/50 lines"
    assert data["cpt-45378"]["reviewed"] is False
    assert "alias not confirmed" in data["cpt-45378"]["notes"]
    assert data["cpt-85027"]["reviewed"] is False  # a blank row changes nothing
