"""An offline demo: a recorded run, replayed from a checked-in JSON file.

`hpa demo --record` captures, from the local database, the discovery trace for the
hospitals near a few Houston ZIPs and the price summaries for a few services. `hpa demo`
replays it with no database, no network and no API key: the fallback for bad Wi-Fi and the
first thing a visitor sees.
"""

import json
import time
from pathlib import Path

from hpa import catalog, compare, scan, store
from hpa.discovery import short_name
from hpa.hospitals import find_hospitals

DEMO_FILE = Path(__file__).resolve().parents[2] / "demo" / "houston.json"
DEFAULT_ZIPS = ["77030", "77380", "77339"]
DEFAULT_SERVICES = ["knee mri", "colonoscopy", "head ct", "cbc", "screening mammogram"]


def record(con, zips=DEFAULT_ZIPS, services=DEFAULT_SERVICES) -> dict:
    out = {"recorded_on": time.strftime("%Y-%m-%d"), "zips": {}, "services": {}}
    hospitals = {}
    for z in zips:
        found = find_hospitals(con, z)
        out["zips"][z] = []
        for h in found:
            hospitals.setdefault(h.ccn, h)
            c = store.cached_discovery(con, h.ccn)
            out["zips"][z].append({
                "ccn": h.ccn, "name": short_name(h), "distance_km": round(h.distance_km, 1),
                "approximate": h.approximate, "steps": (c or {}).get("steps", []), "ok": bool(c and c["ok"]),
                "reason": (c or {}).get("reason"), "mrf_url": (c or {}).get("mrf_url"),
            })
    for q in services:
        r = catalog.resolve(q)
        if r.verdict != catalog.SELECTED:
            continue
        svc = r.service
        entry = {"service": svc.name, "codes": svc.code_list, "reviewed": svc.reviewed, "hospitals": []}
        codes = [c for _, c in svc.codes]
        for h in hospitals.values():
            c = store.cached_discovery(con, h.ccn)
            if not (c and c["ok"]):
                entry["hospitals"].append({"name": short_name(h), "verdict": "no price file located"})
                continue
            ext = scan.latest_extraction(con, c["mrf_url"])
            if not ext:
                entry["hospitals"].append({"name": short_name(h), "verdict": "not scanned"})
                continue
            rows = con.execute(
                """
                SELECT ic.code_type, ic.code, i.description, ch.setting, ch.billing_class, ch.modifiers,
                       ch.gross, ch.discounted_cash, ch.minimum, ch.maximum, ch.source_ref
                FROM charges ch JOIN items i USING (extraction_id, item_id) JOIN item_codes ic USING (extraction_id, item_id)
                WHERE ch.extraction_id = ? AND ic.code_type IN ('CPT', 'HCPCS', 'MS-DRG', 'DRG') AND list_contains(?, ic.code)
                ORDER BY ic.code, ch.modifiers NULLS FIRST, ch.setting, ch.billing_class, ch.source_ref
                """,
                [ext["extraction_id"], codes],
            ).fetchall()
            lines = [compare.Line(ct, code, (), d, st, bc, m, g, cash, mn, mx, ref) for ct, code, d, st, bc, m, g, cash, mn, mx, ref in rows]
            s = compare.summarise(compare.apply_review(lines, svc.reviewed, short_name(h)))
            hl = s.headline
            entry["hospitals"].append({
                "name": short_name(h), "file_date": ext.get("last_updated_on"), "url": c["mrf_url"],
                "verdict": s.verdict, "detail": s.detail, "lines": len(lines),
                "headline": None if hl is None else {
                    "cash": hl.discounted_cash, "gross": hl.gross, "min": hl.minimum, "max": hl.maximum,
                    "context": hl.context, "ref": hl.source_ref, "description": hl.description,
                },
            })
        out["services"][q] = entry
    return out


def replay(data: dict, out=print, delay: float = 0.0) -> None:
    money = lambda v: f"${v:,.2f}" if v is not None else "—"
    out(f"recorded run from {data['recorded_on']} (no network, no database, no API key)")
    for z, hospitals in data["zips"].items():
        out(f"\nnearest {len(hospitals)} hospitals to the centre of {z}")
        for h in hospitals:
            out(f"  {'~' if h['approximate'] else ''}{h['distance_km'] / 1.609344:.1f} mi  {h['name']}")
        for h in hospitals:
            for step in h["steps"]:
                out(f"{h['name']}: {step}")
                if delay:
                    time.sleep(delay)
    for q, entry in data["services"].items():
        out(f"\n\"{q}\" -> {entry['service']} ({entry['codes']})  [{'reviewed' if entry['reviewed'] else 'unreviewed'}]")
        for h in entry["hospitals"]:
            hl = h.get("headline")
            line = f"  {h['name']:<42} {h['verdict']}"
            if hl:
                line += f"  cash {money(hl['cash'])}  gross {money(hl['gross'])}  [{hl['context']}]  {hl['ref']}"
            out(line)
