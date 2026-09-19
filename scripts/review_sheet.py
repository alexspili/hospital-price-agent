"""Write docs/mapping-review.md: what the scanned files say for a few catalog services, laid
out for a person to confirm the mapping and record how hospitals represent the service.

Usage: python scripts/review_sheet.py "knee mri" colonoscopy "head ct" cbc "screening mammogram"
"""

import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from hpa import catalog, compare, scan, store
from hpa.targets import located
from hpa.discovery import short_name

ZIPS = ["77030", "77380", "77339"]
OUT = Path(__file__).resolve().parents[1] / "docs" / "mapping-review.md"


def money(v):
    return f"${v:,.2f}" if v is not None else "—"


def main(queries: list[str]) -> int:
    con = store.connect(store.DEFAULT_DB, read_only=True)
    targets = [(h, c) for h, c in located(con, ZIPS, None, 5) if c and c["ok"]]
    parts = [
        "# Mapping review sheet\n",
        f"*Generated {date.today()} by `scripts/review_sheet.py` from the scanned Houston files. "
        "For each service: does the plain-English alias mean this CMS entry, and how do the "
        "files represent it (billing class, modifiers, extra lines)? Fill in the **Decision** "
        "block; the answers go into `shoppable_services.json` as `reviewed`.*\n",
    ]
    for q in queries:
        r = catalog.resolve(q)
        if r.verdict != catalog.SELECTED:
            parts.append(f"\n## {q!r}: resolver says {r.verdict} ({r.reason})\n")
            continue
        svc = r.service
        parts.append(f"\n## {q!r} → {svc.name} ({svc.code_list})\n")
        parts.append(f"Aliases: {', '.join(svc.aliases)}. Qualifiers: {svc.qualifiers or 'none'}. Notes: {svc.notes or 'none'}\n")
        codes = [c for _, c in svc.codes]
        verdicts = defaultdict(int)
        for h, c in targets:
            ext = scan.latest_extraction(con, c["mrf_url"])
            if not ext:
                continue
            rows = con.execute(
                """
                SELECT ic.code_type, ic.code,
                       (SELECT list(o.code_type || ' ' || o.code ORDER BY o.code_type, o.code) FROM item_codes o
                         WHERE o.extraction_id = ic.extraction_id AND o.item_id = ic.item_id AND NOT (o.code_type = ic.code_type AND o.code = ic.code)),
                       i.description, ch.setting, ch.billing_class, ch.modifiers, ch.gross, ch.discounted_cash, ch.minimum, ch.maximum,
                       ch.source_ref, ch.off_template_note
                FROM charges ch JOIN items i USING (extraction_id, item_id) JOIN item_codes ic USING (extraction_id, item_id)
                WHERE ch.extraction_id = ? AND ic.code_type IN ('CPT', 'HCPCS', 'MS-DRG', 'DRG') AND list_contains(?, ic.code)
                ORDER BY ic.code, ch.modifiers NULLS FIRST, ch.setting, ch.billing_class, ch.source_ref
                """,
                [ext["extraction_id"], codes],
            ).fetchall()
            lines = [compare.Line(ct, code, tuple(o or []), d, st, bc, m, g, cash, mn, mx, ref, note)
                     for ct, code, o, d, st, bc, m, g, cash, mn, mx, ref, note in rows]
            s = compare.summarise(lines)
            verdicts[s.verdict] += 1
            parts.append(f"\n**{short_name(h)}** — file dated {ext.get('last_updated_on')}, `{c['mrf_url'][:90]}…`  \n")
            parts.append(f"verdict: *{s.verdict}*{' — ' + s.detail if s.detail else ''}\n")
            if lines:
                parts.append("\n| description as written | codes | context | cash | gross | min–max | ref |\n|---|---|---|---|---|---|---|\n")
                for l in lines[:12]:
                    extra = ", ".join(l.other_codes)
                    parts.append(f"| {l.description[:70]} | {l.code_type} {l.code}{' + ' + extra if extra else ''} | {l.context} | {money(l.discounted_cash)} | {money(l.gross)} | {money(l.minimum)}–{money(l.maximum)} | {l.source_ref} |\n")
                if len(lines) > 12:
                    parts.append(f"\n*… {len(lines) - 12} more lines; `hpa prices \"{q}\" --ccn {h.ccn} --all`*\n")
        parts.append(f"\nVerdicts across hospitals: {dict(verdicts)}\n")
        parts.append(
            "\n**Decision** (edit in place):\n"
            "- [ ] The alias means this service: yes / no / needs a qualifier (which?)\n"
            "- [ ] Hospitals represent it as: facility line / professional line / both / varies\n"
            "- [ ] Lines that should NOT count as this service (modifiers, revenue codes, bundles):\n"
            "- [ ] Reviewer, date:\n"
        )
    OUT.write_text("".join(parts))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["knee mri", "colonoscopy", "head ct", "cbc", "screening mammogram"]))
