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
| Hospitals per run | The nearest 5 (a fixed count, not a radius: every hospital is a multi-GB scan). A separate hard cap limits how many files one run may download. |
| Prices | Cash price, gross charge, min/max negotiated only. No payer-level rates. |
| Procedures | A catalog of the 70 CMS-specified shoppable services. Claude maps user text to a catalog entry or asks which variant; it never invents codes. Each entry is `verified` or `unverified`. |
| Distribution | Public repo + hosted demo |
| Model | Claude API with tool use + structured output, **for the fuzzy steps only**. Orchestration is plain Python. |
| Store | DuckDB, file-backed, committed empty |
| Hosted demo | Cache-first: pre-scanned Houston ZIPs (77030, 77380, 77024) answer instantly; "run live" is opt-in |
| Cadence | Built in public: repo goes public at milestone 1 and grows weekly |

### Where Claude is used, and where it is not

The pipeline is deterministic code: geography, HTTP, streaming parses, SQL. Claude is called
only where the input is fuzzy:

- user text → one catalog entry (or a clarifying question: "with or without contrast?")
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
- Each hospital must serve `cms-hpt.txt` at its root domain, pointing to the file location.
  In practice the **health system** serves it and lists many locations (`location-name`,
  `source-page-url`, `mrf-url`). Matching a CMS hospital to the right entry is a real step.
- Compliance is uneven. Missing `cms-hpt.txt`, dead links, redirects, login walls and
  off-template layouts are all normal. They are cases to handle, not crashes.
- Hospital names, addresses and ZIP codes come from CMS's Hospital General Information
  dataset. It has no URLs and no coordinates, omits PPS-exempt cancer hospitals (e.g. MD
  Anderson), and includes federal hospitals, which are exempt from the rule (excluded by default).
- Coordinates: geocode every street address with the Census Geocoder batch endpoint at
  setup (~85% match). Fall back to the ZIP centroid (Census ZCTA gazetteer), flagged. Never
  guess from nearby ZIP *numbers*; ZIP numbering says nothing about geography. Hospitals
  with neither stay unresolved and are excluded from "nearest", never silently placed.
- CPT descriptors are AMA-copyrighted. Do not commit a CPT description table. The catalog
  uses CMS's own plain-English service names; HCPCS Level II and MS-DRG data are public.
- Files run from hundreds of MB to several GB. **Always stream-parse** (`ijson` for JSON,
  a streaming reader for CSV). Never load a whole file into memory. Never commit one.

### The four price columns

Every file carries these per item, regardless of which payers it lists:

- **Gross charge** — chargemaster list price. Nearly nobody pays it.
- **Discounted cash price** — what a self-pay patient is charged. The most comparable
  number across hospitals and the headline figure in results.
- **Min / max negotiated rate** — lowest and highest across all contracts, unnamed.

Some entries are percentages or algorithms rather than dollar amounts. Surface those as
what they are; never convert them into dollars.

### What makes two rows comparable

A CMS item can carry several codes and several charges that differ by billing class
(facility vs professional), modifiers, setting (inpatient/outpatient) and drug units. Two
rows that share a code are **not** automatically the same service. The comparison must
check billing class, setting, modifiers and units, and report "not comparable, because …"
when they differ. This is what the catalog's `verified` flag certifies, per service.

## Steps

1. `find_hospitals(zip, limit=5)` → the nearest hospitals from the CMS dataset
2. `find_hospital_website(hospital)` → web search + Claude picks the official domain
3. `locate_price_file(hospital)` → try `cms-hpt.txt` (matching the hospital to its entry),
   then common paths, then a web search. Return the URL and the method that found it, or a
   stated reason for failure.
4. `map_to_catalog(query)` → one catalog entry, or a clarifying question
5. `scan_file(url)` → stream the file, store **every** item, report progress
6. `compare(service, hospitals)` → side-by-side comparison with per-row provenance and
   explicit "not comparable" verdicts

## Storage

Separate what was fetched from what it contained from who it belongs to:

| Table | Key | Holds |
|---|---|---|
| `files` | checksum | template version, `last_updated_on` from the header, parser version, size |
| `fetches` | url + fetched_at | HTTP validators (`ETag`, `Last-Modified`, `Content-Length`), status, resulting checksum or failure reason |
| `hospital_files` | ccn + url | how the match was made (`cms-hpt`, `common-path`, `search`, `manual`), when |
| `items` | checksum + item_id | description, setting, billing class, drug unit/type, `methodology`, source row number or JSON path |
| `item_codes` | checksum + item_id + code | code type, code, modifiers |
| `item_prices` | checksum + item_id | the four columns as DECIMAL, plus `non_dollar_note` for percentages/algorithms |
| `catalog_cache` | normalised query + model + prompt version + catalog version | catalog entry chosen, or the clarification asked |

One file shared by several hospitals is stored once and linked from `hospital_files` many
times. Provenance is never overwritten.

## Caching

Every expensive step is cached, so a repeat search never repeats the work.

- **Check before downloading.** A HEAD request (or a 1-byte range GET where HEAD is refused)
  compares `ETag` and `Last-Modified`. If both are missing, read the first 64 KB and compare
  the `last_updated_on` in the file header. If that's missing too, re-download after 7 days.
  `Content-Length` alone never proves a file is unchanged.
- **The checksum is recorded after download** as provenance, not as the freshness test.
- **Store all items on first scan** (20k–100k per file; small with only the four columns).
  Any later service at that hospital is a SQL query with no network.
- **Cache keys include versions**: parser version for extractions; model, prompt and
  catalog version for query mappings. Bumping a version invalidates only that cache.
- **Failures are cached** with reason and time, expiring after 7 days.
- Discovery results (website, file URL) expire after 30 days or when the URL stops resolving.
- The trace says when a cached result is used, e.g.
  `Methodist The Woodlands: price file unchanged since 2026-09-12, using cached rows`.

## Behaviour rules

- Never invent a price. A hospital that could not be resolved is reported as missing, with
  the reason.
- Every number carries its source file URL, row or JSON path, and the file's date.
- Unverified catalog entries still return results, labelled unverified.
- When Claude cannot map the query to one entry, ask; never scan on a guess.
- Hospitals are processed in parallel, so the wait is the slowest file, not the sum.
- Progress while scanning is a moving row counter, never a spinner.
- Non-positive limits, negative caps and similar are rejected at the boundary, not passed through.

## Trace output

The left pane shows the work as it happens, one line per event:

```
nearest 5 hospitals to 77380
"knee MRI" -> MRI scan of leg joint (CPT 73721)  [unverified]
Methodist The Woodlands: cms-hpt.txt found -> price file 2.1 GB, scanning
St. Luke's Woodlands: cms-hpt.txt missing, searching site
HCA Houston Conroe: price file unchanged since 2026-09-12, using cached rows
Methodist The Woodlands: 2 matching rows after 1.4M scanned
St. Luke's Woodlands: no machine-readable file located — skipped
```

## Milestones

1. Scaffold. CMS hospital dataset loaded and geocoded, DuckDB store, `find_hospitals`
   working, the 70-service catalog, CI, lock file, offline tests.
2. Discovery: `find_hospital_website` + `locate_price_file` against ~10 real Houston-area
   hospitals. Record what breaks and how often; publish `docs/houston-compliance-findings.md`.
   Measure hospital-to-file match accuracy on that set.
3. Streaming extraction with the storage and caching above, v3.0 first. Parser fixtures
   (small excerpts of each shape) in the repo. Report scan time, peak memory, cache speed-up
   and failure counts on named files.
4. One complete Houston example: 5 hospitals, one service category, real prices, links to
   the source rows. First hand-verified catalog entries. `hpa demo` runs it offline from
   checked-in results with no API key.
5. Pipeline with Claude at the fuzzy steps, CLI trace. Eval harness reporting **four numbers
   separately**: hospital match accuracy, extraction accuracy, comparison eligibility, and
   unresolved cases. All in the README.
6. FastAPI + server-sent events, React split-pane UI. Simpler than first planned; the
   trace is the feature.
7. Deploy.

## Hosted demo constraints

Milestone 7 only. Do not build these earlier.

- Scans take minutes. Run them as background jobs with progress over SSE or polling,
  never inside a request cycle.
- Landing state is pre-scanned Houston ZIPs; a live scan is an explicit opt-in.
- Per-IP rate limit, a hard daily API spend cap, and the per-run download cap.
- Queue depth limit with an honest "busy, try again" message.
- Keep a recorded run checked in as a fallback for demos on bad Wi-Fi.

## README requirements

- Lead with what works today; the target trace comes after
- 30-second demo GIF once there is something to show
- Architecture diagram
- The four eval numbers, and the verified-services count
- Measured engineering results from milestone 3
- Honest limitations section
- Positioning: cash-price exploration and data-quality analysis. Payer-level contract
  analysis is out of scope and the README says so.
