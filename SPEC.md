# Live hospital price agent — build spec

Given a ZIP code and a plain-English procedure, an agent discovers nearby hospitals, finds
their price transparency files on the live web, extracts the relevant rows, and compares
them — streaming every step to the screen as it happens. The visible work is the point of
the project, not a side effect of it.

## Locked decisions

Do not revisit these without asking.

| Decision | Choice |
|---|---|
| Stack | Python core (FastAPI) + small TypeScript/React frontend |
| Interface | Local web page, split pane: trace left, results right |
| Discovery | Fully live from a ZIP — hospitals *and* file locations |
| Prices | Cash price, gross charge, min/max negotiated only. No payer-level rates. |
| Procedures | Any procedure; an LLM maps it to CPT/HCPCS/MS-DRG codes |
| Distribution | Public repo + hosted demo |
| Model | Claude API with tool use + structured output, **for the fuzzy steps only** (see below). Orchestration is plain Python. |
| Store | DuckDB, file-backed, committed empty |
| Hosted demo | Cache-first: pre-scanned Houston ZIPs (77030, 77380, 77024) answer instantly; "run live" is opt-in |
| Cadence | Built in public: repo goes public at milestone 1 and grows weekly |

### Where Claude is used, and where it is not

The pipeline is deterministic code: geography, HTTP, streaming parses, SQL. Claude is called
only where the input is fuzzy:

- plain-English procedure → CPT / HCPCS / MS-DRG candidates
- hospital → its website (the CMS dataset has no URLs)
- hospital → its entry in a system-level `cms-hpt.txt` (after a fuzzy string match fails to decide)
- off-template file layouts → column mapping

Everything else is testable without an API key. That's what makes the eval harness meaningful.

## Domain background

- Since 1 July 2024, hospitals must publish a machine-readable standard charges file in
  CMS's standard template. Three shapes exist: CSV wide, CSV tall, and JSON.
- Each hospital must serve `cms-hpt.txt` at its root domain, pointing to the file location.
- Compliance is uneven. Missing `cms-hpt.txt`, dead links, redirects, login walls and
  off-template layouts are all normal. They are cases to handle, not crashes.
- Hospital names, addresses and ZIP codes come from CMS's public Hospital General
  Information dataset. It has **no website URLs and no coordinates**, and it omits
  PPS-exempt cancer hospitals (e.g. MD Anderson). Federal (VA, DoD) hospitals are exempt from
  the price transparency rule and are excluded by default.
- Distance is ZIP centroid to ZIP centroid, using the Census ZCTA gazetteer. About 2.5% of
  hospital ZIPs are PO-box ZIPs with no ZCTA; those fall back to the numerically nearest
  ZCTA in the same 3-digit prefix and are flagged as approximate.
- `cms-hpt.txt` is usually served by the **health system**, not the individual hospital, and
  lists many locations (`location-name`, `source-page-url`, `mrf-url`). Matching a CMS
  hospital to the right entry is a real step, not a lookup.
- The template has versions (2.0, 2.1, 2.2, and the 2026 revisions). Detect the version from
  the file header; unsupported versions are reported as "off-template" with the reason.
- CPT descriptors are AMA-copyrighted. Do not commit a CPT description table. Check code
  mappings against the descriptions inside the price files themselves. HCPCS Level II and
  MS-DRG reference data are public and fine to ship.
- Files run from hundreds of MB to several GB. **Always stream-parse** (`ijson` for JSON,
  a streaming reader for CSV). Never load a whole file into memory. Never commit one.

### The four price columns

Every file carries these per code, regardless of which payers it lists:

- **Gross charge** — chargemaster list price. Nearly nobody pays it.
- **Discounted cash price** — what a self-pay patient is charged. The most comparable
  number across hospitals and the headline figure in results.
- **Min / max negotiated rate** — lowest and highest across all contracts, unnamed.

Some entries are percentages or algorithms rather than dollar amounts. Surface those as
what they are; never convert them into dollars.

## Agent tools

1. `find_hospitals(zip, radius_km)` → nearby hospitals from the CMS dataset
2. `find_hospital_website(hospital)` → web search + Claude picks the official domain
3. `locate_price_file(hospital)` → try `cms-hpt.txt` (matching the hospital to its entry),
   then common paths, then a web search. Return the URL and the method that found it, or a
   stated reason for failure.
4. `map_procedure_to_codes(query)` → candidate codes with confidence scores
5. `scan_file(url, codes)` → stream the file, keep matching rows, report progress
6. `compare(rows)` → side-by-side comparison with per-row provenance

## Behaviour rules

- Never invent a price. A hospital that could not be resolved is reported as missing, with
  the reason.
- Every number carries its source file URL and the file's date.
- Low-confidence code mappings ask the user before scanning anything.
- Hospitals are processed in parallel, so the wait is the slowest file, not the sum.
- Progress while scanning is a moving row counter, never a spinner.

## Trace output

The left pane shows the agent's work as it happens, one line per event:

```
found 4 hospitals within 25 km of 77380
mapped "knee MRI" -> 73721, 73723 (confidence 0.91)
Methodist The Woodlands: cms-hpt.txt found -> price file 2.1 GB, scanning
St. Luke's Woodlands: cms-hpt.txt missing, searching site
HCA Houston Conroe: price file found, 840 MB, scanning
Methodist The Woodlands: 2 matching rows after 1.4M scanned
St. Luke's Woodlands: no machine-readable file located — skipped
```

## Milestones

1. Scaffold. CMS hospital dataset loaded, DuckDB store, `find_hospitals` working.
2. `find_hospital_website` + `locate_price_file` against ~10 real Houston-area hospitals.
   Record what breaks and how often — this list drives the fallback logic. Publish it as
   `docs/houston-compliance-findings.md`.
3. Streaming extraction into DuckDB, keyed by hospital plus file checksum.
4. Pipeline with Claude calls at the fuzzy steps, structured output. CLI trace first.
5. FastAPI + server-sent events, React split-pane UI.
6. Eval harness: 20 hand-checked questions, accuracy reported in the README.
7. Deploy.

## Hosted demo constraints

Milestone 7 only. Do not build these earlier.

- Scans take minutes. Run them as background jobs with progress over SSE or polling,
  never inside a request cycle.
- Cache extraction results by file checksum. A repeat area answers in seconds.
- Per-IP rate limit and a hard daily API spend cap.
- Queue depth limit with an honest "busy, try again" message.
- Landing state is pre-scanned Houston ZIPs; a live scan is an explicit opt-in.
- Keep a recorded run checked in as a fallback for demos on bad Wi-Fi.

## README requirements

- 30-second demo GIF at the top
- Architecture diagram
- The eval accuracy number
- Honest limitations section
- A short note on who actually buys this data — self-insured employers, benefits brokers,
  patient advocacy services — and why consumer price shopping mostly does not work
