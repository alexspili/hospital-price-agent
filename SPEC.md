# Live hospital price agent — build spec

Given a ZIP code and one of CMS's 70 shoppable services, the system finds the nearest
hospitals, finds their price transparency files on the live web, extracts the relevant rows,
and compares them — streaming every step to the screen as it happens. The visible work is
the point of the project, not a side effect of it.

## Locked decisions

Do not revisit these without asking.

| Decision | Choice |
|---|---|
| Stack | Python core (FastAPI) + small TypeScript/React frontend |
| Interface | Local web page, split pane: trace left, results right |
| Discovery | Fully live from a ZIP — hospitals *and* file locations |
| Hospitals per run | The nearest 5 (a fixed count, not a radius: every hospital is a multi-GB scan). A hospital whose file cannot be located keeps its slot and is shown as skipped; the search does not advance to the sixth. A separate hard cap limits downloads per run. |
| Prices | Cash price, gross charge, min/max negotiated only. No payer-level rates. |
| Procedures | A catalog of the 70 CMS-specified shoppable services. A deterministic resolver picks an entry or says why it can't; Claude confirms or asks; nothing invents codes. |
| Distribution | Public repo + hosted demo |
| Model | Claude API with tool use + structured output, **for the fuzzy steps only**. Orchestration is plain Python. |
| Store | DuckDB, file-backed, committed empty. One process owns the file at a time (see Process model). |
| Hosted demo | Cache-first: pre-scanned Houston ZIPs (77030, 77380, 77024) answer instantly; "run live" is opt-in |
| Cadence | Built in public: repo goes public at milestone 1 and grows weekly |

### Where Claude is used, and where it is not

The pipeline is deterministic code: geography, HTTP, streaming parses, SQL. Claude is called
only where the input is fuzzy:

- confirming the resolver's catalog pick, or asking the clarifying question it raised
- hospital → its website (the CMS dataset has no URLs)
- hospital → its entry in a system-level `cms-hpt.txt` (after a fuzzy string match fails to decide)
- off-template file layouts → column mapping

Everything else is testable without an API key. That's what makes the eval meaningful.

## Domain background

- Hospitals have had to publish standard charges since 1 January 2021 (45 CFR 180). Since
  1 July 2024 the machine-readable file must follow CMS's template. **Data dictionary v3.0**
  is current: effective 1 January 2026, enforced from 1 April 2026. Three shapes exist: CSV
  wide, CSV tall, and JSON.
- Support v3.0 first and v2.x as legacy. Read the version from the file header; anything
  else is reported as "off-template" with the reason.
- In the four summary columns (gross, discounted cash, min, max) the template allows
  dollars only. Percentages, algorithms and `methodology` exist only on payer-specific
  columns, which are out of scope. Non-numeric text that a hospital puts in a dollar column
  anyway is a data-quality finding: keep it verbatim in `off_template_note`, never coerce.
- The **tall** CSV repeats the four summary columns on every payer × plan row, so one item
  appears hundreds of times. An item's identity is (description, all codes with types,
  setting, billing class, modifiers, drug unit and type); tall rows are deduplicated on
  that key while streaming. If rows for the same item **disagree** on a summary price,
  nothing is chosen: every distinct value is kept with its source row number, the item is
  flagged `conflicting_summary`, and the comparison reports it as `unknown`.
- Each hospital must serve `cms-hpt.txt` at its root domain, pointing to the file location.
  In practice the **health system** serves it and lists many locations (`location-name`,
  `source-page-url`, `mrf-url`). Matching a CMS hospital to the right entry is a real step.
- Compliance is uneven. Missing `cms-hpt.txt`, dead links, redirects, login walls and
  off-template layouts are all normal. They are cases to handle, not crashes.
- The 70 CMS-specified services govern the consumer-friendly display, "where offered".
  Hospitals may substitute or cross-walk codes. A service missing from a file is not by
  itself non-compliance and is reported as "not found", not "not published".
- Hospital names, addresses and ZIP codes come from CMS's Hospital General Information
  dataset. It has no URLs and no coordinates and omits PPS-exempt cancer hospitals (e.g. MD
  Anderson). Only federal hospitals (VA, DoD) are exempt from the rule and excluded by
  default; psychiatric, children's, long-term and rural emergency hospitals are included.
- Coordinates: geocode every street address with the Census Geocoder batch endpoint at
  setup (~85% match; points are interpolated along the street's address range, not
  rooftops). Heuristic sanity check: reject a geocode that lies more than 3 × the ZIP's
  equivalent radius + 2 km from the ZIP centroid, with a note. Fall back to the ZIP
  centroid: show that distance as approximate (`~2.1 mi, ZIP centroid`) and carry the
  ZIP's equivalent radius as a separate uncertainty figure. It is **not** a bound (ZIPs
  are not circles) and it is not folded into the ranking; ranking is by estimated distance
  at full precision, with exact ties going to the better-located hospital. Defensible
  bounds would need the ZCTA boundary geometry, which is not worth carrying yet. Never
  guess from nearby ZIP *numbers*. Hospitals with neither stay unresolved and are excluded
  from "nearest", never silently placed.
- CPT descriptors are AMA-copyrighted. Do not commit a CPT description table. The catalog
  uses CMS's own plain-English service names; HCPCS Level II and MS-DRG data are public.
- Files run from hundreds of MB to several GB. **Always stream-parse** (`ijson` for JSON,
  a streaming reader for CSV). Never load a whole file into memory. Never commit one.

### The four price columns

Every file carries these per charge, regardless of which payers it lists:

- **Gross charge** — chargemaster list price. Nearly nobody pays it.
- **Discounted cash price** — what a self-pay patient is charged. The most comparable
  number across hospitals and the headline figure in results.
- **Min / max negotiated rate** — lowest and highest across all contracts, unnamed.

### Two checks that must stay separate

1. **Mapping reviewed** (a property of a catalog entry): a person has confirmed that the
   entry's aliases mean this service and recorded how hospital files represent it. Stored
   on the entry with reviewer, date and the file checksums looked at.
2. **Comparable** (a property of one comparison, computed from the rows): the matched
   charges share setting, billing class, modifiers and units. Verdicts are `comparable`,
   `not comparable, because …`, or `unknown` when any of that context is missing on either
   side. Two missing values are never treated as a match. Every result carries the verdict.

A reviewed mapping says nothing about comparability, and vice versa.

## The catalog

One entry per CMS service, in `src/hpa/data/shoppable_services.json`:

| Field | Purpose |
|---|---|
| `id` | `cpt-73721`, `drg-470`, `cpt-81000-81001`; used as the cache and provenance key |
| `codes` | (type, code) pairs as CMS printed them |
| `qualifiers` | variants the CMS name leaves implicit: `{"contrast": "without"}`, `{"biopsy": "with"}` |
| `aliases` | plain-English search terms, added by this project |
| `notes` | how hospital files actually represent it (global vs facility code, add-on codes, OB packages → DRGs) |
| `expected_billing_class`, `expected_setting` | what a comparable hospital row should say (added at milestone 3, from the discovery findings) |
| `alternate_codes` | codes hospitals substitute (93005 for 93000) (milestone 3) |
| `hospital_types` | which hospital types plausibly offer it, to keep children's hospitals out of adult searches and psychiatric hospitals in psychotherapy searches (milestone 3) |
| `reviewed` | mapping review evidence: reviewer, date, checksums (milestone 4) |

`resolve(query)` is deterministic and returns a verdict with candidates: `selected`,
`ambiguous` (ties; ask), `unsupported variant` (the service exists but not in the variant
asked for; never substitute a different organ), `needs clarification` (the query asks for
a qualifier the entry does not declare, e.g. "knee MRI with biopsy", or contradicts
itself; never assume, never let pattern order pick), or `not in catalog` (some query word
matched nothing; the closest entries are shown but nothing is selected). Regression tests
pin "knee mri with contrast", "colonoscopy without biopsy", "knee mri with biopsy",
"knee mri with contrast without contrast", "mri", "chest x-ray".

## Steps

1. `find_hospitals(zip, limit=5)` → the nearest hospitals from the CMS dataset
2. `find_hospital_website(hospital)` → web search + Claude picks the official domain
3. `locate_price_file(hospital)` → try `cms-hpt.txt` (matching the hospital to its entry),
   then common paths, then a web search. Return the URL and the method that found it, or a
   stated reason for failure.
4. `resolve(query)` → verdict + candidates; Claude confirms or asks
5. `scan_file(url)` → stream the file, store **every** item and charge, report progress
6. `compare(service, hospitals)` → side-by-side with per-charge provenance and a
   comparability verdict on every pair

## Storage

Separate what was fetched from what it contained from who it belongs to, and give every
charge its own identity:

| Table | Key | Holds |
|---|---|---|
| `sources` | name + fetched_at | reference data provenance: URL, dataset release date, row count, sha256, geocoder benchmark. Printed by `hpa hospitals --verbose` and in the trace |
| `fetches` | url + fetched_at | HTTP validators (`ETag`, `Last-Modified`, `Content-Length`), status, header `last_updated_on`, resulting checksum or failure reason |
| `files` | checksum | template version, shape, `last_updated_on`, size, hospital-declared attester |
| `extractions` | checksum + parser_version | when, row count, duration, peak memory, warnings. A parser fix produces a new extraction, never edits an old one |
| `hospital_files` | ccn + url | how the match was made (`cms-hpt`, `common-path`, `search`, `manual`), when, by what evidence |
| `items` | extraction + item_id | description, drug unit and type, source row number or JSON path, `off_template_note` |
| `item_codes` | extraction + item_id + code_type + code | one row per code on the item |
| `charges` | extraction + charge_id | item_id, setting, billing class, modifiers, the four columns as DECIMAL (NULL when blank/N-A, with the raw text kept in `off_template_note`) |
| `catalog_cache` | normalised query + model + prompt version + catalog version | verdict and entry chosen, or the clarification asked |

One file shared by several hospitals is stored once and linked from `hospital_files` many
times. Provenance is never overwritten.

## Caching

Every expensive step is cached, so a repeat search never repeats the work.

- **Check before downloading.** A HEAD request (or a range GET for the first 64 KB, where
  HEAD is refused) compares `ETag` and `Last-Modified`; if those are missing, compare the
  header's `last_updated_on`. If the server ignores the range and streams the whole file,
  read 64 KB and close the connection; never buffer the response.
- **Maximum age regardless.** A cached extraction older than 30 days is refreshed even if
  no validator changed: hospitals change prices without touching the header date. The
  trace says "no change detected since <date>", never "unchanged".
- **The checksum is recorded after download** as provenance, not as the freshness test.
- **Store all items and charges on first scan.** Any later service at that hospital is a
  SQL query with no network.
- **Cache keys include versions**: parser version for extractions; model, prompt and
  catalog version for query mappings. Bumping a version invalidates only that cache.
- **Failures are cached** with reason and time, expiring after 7 days.
- Discovery results (website, file URL) expire after 30 days or when the URL stops resolving.
- The trace says when a cached result is used, e.g.
  `Methodist The Woodlands: no change detected since 2026-09-12, using cached rows`.

## Process model

DuckDB allows one writer per file, and while a writer holds the file **no other process
can open it, even read-only** (verified: the reader fails with a lock error). So:

- The web server owns the single connection and runs scans as tasks inside that process
  (asyncio + a thread pool for parsing).
- While the server is running, the CLI sends queries to the server's HTTP API instead of
  opening the file. When no server is running, the CLI opens the file directly, read-only.
- Fallback for tools that must read the file while the server is up: the server writes a
  read-only snapshot copy on a schedule (`EXPORT`/copy after each scan), and readers open
  that.
- `hpa setup` holds an exclusive lock for its whole run (downloads through the final
  rename), builds into a uniquely named temporary file, validates it (row counts, share of
  hospitals located by address when geocoding was attempted), refuses to replace a
  database another process has open, and only then swaps it in with an atomic rename. A failed build leaves the
  existing database untouched. Once price tables exist, `setup` refreshes only the
  reference tables inside a transaction; wiping caches is a separate, explicit `--reset`.

## Behaviour rules

- Never invent a price. A hospital that could not be resolved is reported as missing, with
  the reason.
- Every number carries its source file URL, row or JSON path, and the file's date.
- Every comparison carries its comparability verdict; `unknown` is a valid answer.
- Unreviewed catalog entries still return results, labelled unreviewed.
- When the resolver is not `selected` and Claude cannot settle it, ask; never scan on a guess.
- Hospitals are processed in parallel, so the wait is the slowest file, not the sum.
- Progress while scanning is a moving row counter, never a spinner.
- Non-positive limits, negative caps and similar are rejected at the boundary.
- Reference-data counts shown anywhere come from the `sources` table, never hardcoded.

## Trace output

The left pane shows the work as it happens, one line per event:

```
nearest 5 hospitals to the centre of 77380
"knee MRI" -> MRI scan of leg joint (CPT 73721)  [mapping unreviewed]
Methodist The Woodlands: cms-hpt.txt found -> price file 2.1 GB, scanning
St. Luke's Woodlands: cms-hpt.txt missing, searching site
HCA Houston Conroe: no change detected since 2026-09-12, using cached rows
Methodist The Woodlands: 2 matching charges after 1.4M rows
St. Luke's Woodlands: no machine-readable file located — skipped
compare: Methodist vs HCA Conroe: comparable (outpatient, facility, no modifiers)
compare: Methodist vs Baylor: unknown (Baylor row has no billing class)
```

## Milestones

1. Scaffold. CMS hospital dataset loaded, geocoded and sanity-checked, DuckDB store,
   `find_hospitals` working, the 70-service catalog with a verdict-giving resolver, CI, lock
   file, offline tests.
2. Discovery (done 2026-09-18): `locate_price_file` against the 15 hospitals nearest
   77030, 77380 and 77339, with a "site page" layer for hosts that exist but serve no index.
   `docs/houston-compliance-findings.md` records what broke. `hpa eval-discovery` compares
   domains with a dated DoltHub snapshot under `eval/`; it overlaps only 2 of 15 hospitals
   and is reported as such. `sources` table exists but is not yet filled by setup.
3. Extraction (done 2026-09-18): streaming readers for all three shapes plus zip, tall
   deduplication with conflicts kept, bulk load through temp CSVs (DuckDB's executemany is
   ~2 ms/row), one HEAD per scan for freshness, on-disk downloads reused after an
   interrupted extraction. 11 of 12 located files extracted (Townsen is an off-template
   chargemaster export); metrics in the README. `hpa prices` gives per-hospital verdicts:
   comparable / unknown (no billing class) / modifier-specific only / negotiated only /
   inpatient only / conflicting / not found. Catalog `expected_*` fields still to fill.
4. Houston example (done 2026-09-19): `demo/houston.json` records 15 hospitals × 5 services
   with verdicts and source refs; `hpa demo` replays it offline. `docs/mapping-review.md`
   (from `scripts/review_sheet.py`) is the sheet for the human mapping review; entries are
   marked `reviewed` only from that sheet.
5. Eval (done 2026-09-19): `hpa eval` reports the four numbers; extraction fidelity re-reads
   sampled charges from the raw files at their source ref (256/256). Claude's third use:
   `confirm_service`, which may only choose among the resolver's candidates or ask.
6. Web UI (done 2026-09-19): `hpa serve` — FastAPI, a run as a background task in the
   process that owns the database, its trace streamed as numbered server-sent events and
   replayable from any sequence number after a dropped connection, results emitted per
   hospital as each file finishes. React + TypeScript split pane in `frontend/`; the
   landing state is `demo/houston.json` served in the same shape as a live run. The
   pipeline itself moved to `hpa/pipeline.py`, which the CLI, the recorded demo and the
   server share. While the server runs, `hpa prices` reads through its API and writing
   commands say who holds the file.
7. Deploy. Built 2026-09-19, not yet live: a run is cache-first unless it asks to be
   live, live scans need a shared PIN, and the per-IP rate limit, per-run download cap and
   daily model budget are read from the environment (`hpa/settings.py`). `hpa export-demo`
   writes the compact database the host runs on; Dockerfile, compose file with Caddy and
   the runbook are in `docs/deploy.md`. Target: a small ARM VM on AWS with a mounted disk.

## Hosted demo constraints

Milestone 7 only. Do not build these earlier.

- Scans take minutes. Run them as tasks in the writer process with progress over SSE,
  never inside a request cycle.
- Landing state is pre-scanned Houston ZIPs; a live scan is an explicit opt-in.
- Per-IP rate limit, a hard daily API spend cap, and the per-run download cap. Spend is
  measured from the tokens the API reports and recorded in `llm_spend`; past the cap the
  deterministic pipeline carries on without Claude rather than failing.
- Queue depth limit with an honest "busy, try again" message.
- Keep a recorded run checked in as a fallback for demos on bad Wi-Fi.
- No interim static demo on GitHub Pages (decided 2026-09-19). Pages could serve the
  recorded run today, but the public URL should arrive once, with live scanning working,
  rather than as a version that cannot do the thing the project claims.

## README requirements

- Lead with what works today, in the present tense only for what exists; the target trace
  and pipeline are labelled as planned
- 30-second demo GIF once there is something to show
- Architecture diagram
- The four eval numbers and the reviewed-mappings count, generated, not typed
- Measured engineering results from milestone 3
- Honest limitations section
- Positioning: cash-price exploration and data-quality analysis. Payer-level contract
  analysis is out of scope and the README says so.
