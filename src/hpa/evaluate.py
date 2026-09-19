"""The four accuracy numbers, kept separate (SPEC.md, milestone 5).

1. Hospital → file: how many hospitals in the run resolved to a probed file, and the
   agreement with the external (dated, weak) index in eval/.
2. Extraction fidelity: a sample of stored charges is re-read from the raw file at its
   recorded source reference (row number or item/charge index) and compared, value by
   value. This checks that provenance really points at the number shown.
3. Comparison eligibility: over service × hospital pairs, the share with each verdict.
4. Unresolved: every hospital that has no usable file, with the reason.

Nothing here is self-graded by a model. Fidelity is checked against the files themselves.
"""

import json
import random
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from hpa import catalog, compare, mrf, scan, store
from hpa.targets import located
from hpa.discovery import _match_tokens, short_name

RESULTS = Path(__file__).resolve().parents[2] / "eval" / "results.json"
INDEX = Path(__file__).resolve().parents[2] / "eval" / "dolthub_hospitals_tx.json"
ZIPS = ["77030", "77380", "77339"]
SERVICES = ["knee mri", "colonoscopy", "head ct", "cbc", "screening mammogram", "lipid panel", "chest x-ray"]


def _ref_key(ref: str):
    m = re.fullmatch(r"row (\d+)", ref)
    if m:
        return ("row", int(m.group(1)), 0)
    m = re.fullmatch(r"item (\d+)/charge (\d+)", ref)
    return ("item", int(m.group(1)), int(m.group(2)))


def verify_sample(con, extraction_id: str, path: Path, n: int, rng: random.Random) -> dict:
    """Re-read `n` random stored charges from the raw file and compare."""
    rows = con.execute(
        "SELECT ch.source_ref, ch.gross, ch.discounted_cash, ch.minimum, ch.maximum, ch.setting, ch.modifiers, "
        "(SELECT list(code ORDER BY code) FROM item_codes ic WHERE ic.extraction_id = ch.extraction_id AND ic.item_id = ch.item_id) "
        "FROM charges ch WHERE ch.extraction_id = ? ORDER BY random() LIMIT ?", [extraction_id, n]
    ).fetchall()
    wanted = {r[0]: r for r in rows}
    checked = matched = 0
    mismatches = []
    _, charges = mrf.open_mrf(str(path))
    for c in charges:
        stored = wanted.get(c.source_ref)
        if stored is None:
            continue
        checked += 1
        same = (
            _eq(c.gross, stored[1]) and _eq(c.discounted_cash, stored[2]) and _eq(c.minimum, stored[3]) and _eq(c.maximum, stored[4])
            and (c.setting or None) == (stored[5] or None) and (c.modifiers or None) == (stored[6] or None)
            and sorted(code for _, code in c.codes) == sorted(stored[7] or [])
        )
        matched += same
        if not same and len(mismatches) < 3:
            mismatches.append({"ref": c.source_ref, "file": [c.gross, c.discounted_cash, c.minimum, c.maximum, c.setting, c.modifiers],
                               "stored": list(stored[1:7])})
        if checked == len(wanted):
            break
    return {"sampled": len(wanted), "checked": checked, "matched": matched, "mismatches": mismatches}


def _eq(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) < 0.005


def run(con, sample: int = 25, seed: int = 0) -> dict:
    rng = random.Random(seed)
    con.execute("SELECT setseed(?)", [seed / 10 % 1])  # reproducible samples
    targets = located(con, ZIPS, None, 5)
    report = {"zips": ZIPS, "hospitals": len(targets)}

    # 1. hospital -> file
    resolved = [(h, c) for h, c in targets if c and c["ok"]]
    report["discovery"] = {"located": len(resolved), "of": len(targets), "by_method": dict(Counter(c["method"] for _, c in resolved))}
    index = json.loads(INDEX.read_text()) if INDEX.exists() else None
    if index:
        from rapidfuzz import fuzz
        agree = differ = 0
        for h, c in resolved:
            best = max(index["rows"], key=lambda r: fuzz.token_sort_ratio(_match_tokens(h.name), _match_tokens(r["name"])))
            if fuzz.token_sort_ratio(_match_tokens(h.name), _match_tokens(best["name"])) < 85:
                continue
            theirs = urlsplit(best["url"]).netloc.lower().removeprefix("www.")
            mine = urlsplit(c["mrf_url"]).netloc.lower().removeprefix("www.")
            same = mine == theirs or mine.endswith("." + theirs) or theirs.endswith("." + mine)
            agree += same
            differ += not same
        report["discovery"]["external_index"] = {"fetched_on": index["fetched_on"], "overlap": agree + differ, "agree": agree, "differ": differ,
                                                 "note": "index URLs date from 2020-2021; disagreements are the index being stale"}

    # 2. extraction fidelity
    fidelity = {"files": 0, "sampled": 0, "matched": 0, "per_file": {}}
    extracted = {}
    for h, c in resolved:
        ext = scan.latest_extraction(con, c["mrf_url"])
        if not ext:
            continue
        extracted[h.ccn] = (h, c, ext)
        paths = list(scan.MRF_DIR.glob(f"{ext['checksum']}.*"))
        if not paths:
            continue
        v = verify_sample(con, ext["extraction_id"], paths[0], sample, rng)
        fidelity["files"] += 1
        fidelity["sampled"] += v["checked"]
        fidelity["matched"] += v["matched"]
        fidelity["per_file"][short_name(h)] = v
    report["fidelity"] = fidelity

    # 3. comparison eligibility
    verdicts = Counter()
    pairs = []
    for q in SERVICES:
        r = catalog.resolve(q)
        if r.verdict != catalog.SELECTED:
            continue
        codes = [code for _, code in r.service.codes]
        for h, c, ext in extracted.values():
            rows = con.execute(
                "SELECT ic.code_type, ic.code, i.description, ch.setting, ch.billing_class, ch.modifiers, ch.gross, ch.discounted_cash, "
                "ch.minimum, ch.maximum, ch.source_ref FROM charges ch JOIN items i USING (extraction_id, item_id) "
                "JOIN item_codes ic USING (extraction_id, item_id) WHERE ch.extraction_id = ? AND ic.code_type IN ('CPT', 'HCPCS', 'MS-DRG', 'DRG') "
                "AND list_contains(?, ic.code)", [ext["extraction_id"], codes]
            ).fetchall()
            lines = [compare.Line(ct, code, (), d, st, bc, m, g, cash, mn, mx, ref) for ct, code, d, st, bc, m, g, cash, mn, mx, ref in rows]
            s = compare.summarise(compare.apply_review(lines, r.service.reviewed, short_name(h)))
            verdicts[s.verdict] += 1
            pairs.append({"service": q, "hospital": short_name(h), "verdict": s.verdict})
    report["comparison"] = {"pairs": len(pairs), "by_verdict": dict(verdicts),
                            "comparable_share": round(verdicts[compare.COMPARABLE] / len(pairs), 3) if pairs else None, "detail": pairs}

    # 4. unresolved
    report["unresolved"] = [
        {"hospital": short_name(h), "stage": "discovery" if not (c and c["ok"]) else "extraction",
         "reason": (c or {}).get("reason") or "no discovery run" if not (c and c["ok"]) else "not extracted (off-template or not scanned)"}
        for h, c in targets if h.ccn not in extracted
    ]
    return report


def print_report(r: dict) -> None:
    d = r["discovery"]
    print(f"hospitals near {', '.join(r['zips'])}: {r['hospitals']}")
    print(f"1. hospital -> file: {d['located']} of {d['of']} located ({d['by_method']})")
    if "external_index" in d:
        e = d["external_index"]
        print(f"   external index ({e['fetched_on']}): {e['overlap']} overlap, {e['agree']} agree, {e['differ']} differ; {e['note']}")
    f = r["fidelity"]
    print(f"2. extraction fidelity: {f['matched']} of {f['sampled']} sampled charges across {f['files']} files re-read from source and matched")
    for name, v in f["per_file"].items():
        flag = "" if v["matched"] == v["checked"] else f"  MISMATCH {v['mismatches']}"
        print(f"   {name:<42} {v['matched']}/{v['checked']}{flag}")
    c = r["comparison"]
    print(f"3. comparison eligibility: {c['pairs']} service x hospital pairs; {c['by_verdict']}")
    print(f"   comparable share: {c['comparable_share']}")
    print(f"4. unresolved: {len(r['unresolved'])}")
    for u in r["unresolved"]:
        print(f"   {u['hospital']:<42} {u['stage']}: {u['reason'][:90]}")
