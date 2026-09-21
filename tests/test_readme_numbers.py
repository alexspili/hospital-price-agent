"""The README's headline numbers are typed by hand, so this is what keeps them honest:
each one is checked against the last `hpa eval` (eval/results.json). When the eval moves,
the README moves with it, or the suite says so."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def numbers_section() -> str:
    text = (ROOT / "README.md").read_text()
    start = text.index("## The numbers")
    return text[start:text.index("\n## ", start + 1)]


def test_the_readme_numbers_are_the_last_eval():
    r = json.loads((ROOT / "eval" / "results.json").read_text())
    s = numbers_section()

    d = r["discovery"]
    assert f"{d['located']} of {d['of']} located" in s
    by = d["by_method"]
    assert f"{by['cms-hpt']} via `cms-hpt.txt`" in s
    assert f"{by['cms-hpt+tie-break']} tie-break" in s and f"{by['web-search+cms-hpt']} web search" in s
    assert f"{by['site-page']} site page" in s
    e = d["external_index"]
    assert f"overlaps {e['overlap']} of them" in s and f"agrees on {e['agree']}" in s

    f = r["fidelity"]
    assert f"{f['matched']} of {f['sampled']} sampled charges" in s

    c = r["comparison"]
    v = c["by_verdict"]
    assert f"{c['pairs']} service × hospital pairs" in s
    assert f"{v['comparable']} comparable" in s
    assert f"{v['unknown: no billing class stated']} unknown (no billing class)" in s
    assert f"{v['not found']} not found" in s
    assert f"{v['conflicting']} conflicting" in s
    assert f"{v['negotiated rates only, no cash or gross price']} negotiated-only" in s
    assert f"{v['modifier-specific lines only']} modifier-only" in s
    assert f"**{round(c['comparable_share'] * 100)}% comparable**" in s
    assert f"{len(r['unresolved'])}: " in s

    m = re.search(r"## The numbers \(`hpa eval`, (\d{4}-\d{2}-\d{2})", s)
    assert m, "the section heading names the date of the eval run"


def test_the_reviewed_count_matches_the_catalog():
    catalog = json.loads((ROOT / "src" / "hpa" / "data" / "shoppable_services.json").read_text())
    reviewed = sum(1 for x in catalog["services"] if x["reviewed"])
    assert f"**Today: {reviewed} of {len(catalog['services'])} reviewed**" in (ROOT / "README.md").read_text()
