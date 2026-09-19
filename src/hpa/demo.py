"""An offline demo: a recorded run, replayed from a checked-in JSON file.

`hpa demo --record` captures, from the local database, the discovery trace for the
hospitals near a few Houston ZIPs and the price summaries for a few services. `hpa demo`
replays it with no database, no network and no API key: the fallback for bad Wi-Fi and the
first thing a visitor sees.
"""

import json
import time
from pathlib import Path

from hpa import catalog, pipeline, store
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
        # The same function the live page and `hpa prices` use, so a recorded run and a
        # live one are the same shape and say the same things.
        entry = {"service": svc.name, "codes": svc.code_list, "reviewed": svc.reviewed,
                 "hospitals": [pipeline.hospital_prices(con, svc, h, store.cached_discovery(con, h.ccn))
                               for h in hospitals.values()]}
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
