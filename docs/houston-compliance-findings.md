# Finding the price files of 15 Houston hospitals: what broke, and how often

*Milestone 2 of [hospital-price-agent](../README.md). Run on 2026-09-18 against the live
web, for the five hospitals nearest each of three ZIP codes: 77030 (Texas Medical Center),
77380 (The Woodlands) and 77339 (Kingwood). Reproduce with `hpa locate 77030 77380 77339`.*

Since July 2024 every hospital must serve a small text file, `cms-hpt.txt`, at the root of
its website, pointing to its machine-readable standard-charges file. This is the story of
trying to follow that pointer for 15 real hospitals with plain code, and what a program has
to cope with along the way.

## Results

| Hospital | Found by | Index | Entry match | File | Size | File date |
|---|---|---|---|---|---|---|
| Baylor St. Luke's Medical Center | cms-hpt.txt on **commonspirit.org** (parent system) | 72 entries | 97, base name beat "(McNair)" | json | 256 MB | 2026-06-10 |
| CHI St. Luke's Lakeside | cms-hpt.txt on commonspirit.org | 72 | 97 | json | 240 MB | 2026-06-10 |
| St. Luke's The Woodlands | cms-hpt.txt on commonspirit.org | 72 | 100 | json | 239 MB | 2026-06-10 |
| Houston Methodist Hospital | cms-hpt.txt (after a banner of instructions) | 20 | 100 | json served as `.ashx` | 72 MB | 2026-03-25 |
| Houston Methodist The Woodlands | cms-hpt.txt | 20 | 100 | json as `.ashx` | 63 MB | 2026-03-25 |
| HCA Houston Healthcare Kingwood | cms-hpt.txt (36 entries, 24 are freestanding ERs) | 36 | 100 | json on Azure blob, SAS-token URL | 860 MB | 2026-05-27 |
| Texas Children's Hospital | cms-hpt.txt | 4 | 97, main campus beat West Campus / Woodlands | zip | 40 MB | 2026-03-18 |
| Kingwood Pines (psychiatric) | cms-hpt.txt redirected into `/wp-content/uploads/` | 1 | 100 | csv | 129 KB | 2026-09-01 |
| Elite Hospital Kingwood | cms-hpt.txt | 1 | 100 on the trade name after "d/b/a" | csv | 415 KB | 2026-06-04 |
| Townsen Memorial | **no index**; standard-charges link on `/pricing-transparency` | — | single file | csv | 3 MB | **2023-01-05** |
| Harris Health (Ben Taub) | cms-hpt.txt on www.harrishealth.org (bare domain times out) | 2 | **ambiguous** by name; **Claude tie-break** picked Ben Taub from the address | zip | 2 MB | 2026-03-27 |
| Texas Orthopedic Hospital | cms-hpt.txt | 1 | 100 | json on Azure blob | — | **published URL returns 403** |
| Memorial Hermann Surgical Hospital Kingwood | cms-hpt.txt on memorialhermann.org | 19 | **not listed** in the system's index | — | — | — |
| The Woodlands Specialty Hospital | **renamed** Woodlands Oaks Hospital; web search returned the old, dead domain | — | — | — | — | not found |
| Woodland Springs (psychiatric) | name guess hit an unrelated site; **Claude web search** found woodlandspringshealth.com, which has an index | 1 | 100 | csv | unknown (no length sent) | 2026-08-12 |

**Deterministic layers alone: 10 of 15 resolved to a probed file, in 15 seconds wall-clock
(hospitals run in parallel; the slowest is Harris Health at 15 s, waiting for the bare
domain to time out).**

**With Claude's two fallbacks: 12 of 15.** Three model calls in total, each cached:
- *Tie-break with the address* (Harris Health): given the two candidates and "1504 Taub
  Loop", it chose Ben Taub, explaining that LBJ Hospital is at 5656 Kelley St. Correct.
- *Web search for the site* (Woodland Springs): the name guess `woodlandsprings.com` is a
  live site that answers every path with the same HTML page and is not the hospital's. The
  search found `woodlandspringshealth.com`, which serves a proper index. Correct.
- *Web search* (The Woodlands Specialty Hospital): the search returned
  `woodlandsspecialtyhospital.com`, which resolves to 0.0.0.0, and noted in passing that
  the hospital is "now branded The Woodlands Oaks Hospital". The parent site, wchh.care,
  does serve an index listing "Woodlands Oaks Hospital" with a file on a vendor host
  (claraprice.net). The pipeline can't get there from CMS's name, and the model's answer
  was the dead domain, not the live one. Reported as not found, which is the truthful
  result for a program that follows CMS's own records.

The three still unresolved are each a different kind of unfixable-by-cleverness: a
hospital that has been renamed since CMS's dataset was compiled, a published URL that its
own host rejects, and a joint-venture hospital absent from its system's index.

**Repeat runs answer from the cache in under a second**, with no network and no model
calls; the trace says "cached result from <date>".

## What broke, by category

Every one of these is now a test fixture or a regression test.

**Where the index lives (4 of 15 not at the obvious place)**
- The index is served by the **health system, not the hospital**: St. Luke's has no
  `cms-hpt.txt` on stlukeshealth.org; CommonSpirit's covers 72 locations across several
  states. Names in the index ("St. Luke's Health - The Woodlands Hospital") differ from
  CMS's ("ST LUKE'S THE WOODLANDS HOSPITAL"), so matching is fuzzy by necessity.
- **Bare domain vs `www.`**: harrishealth.org hangs; www.harrishealth.org answers. A
  browser-like User-Agent is also needed there.
- **Redirect into a CMS upload folder**: Kingwood Pines answers `/cms-hpt.txt` with a 301
  to `/wp-content/uploads/2025/08/cms-hpt.txt`. Fine, as long as redirects are followed.
- **No index at all, but a linked file**: Townsen Memorial has a "Pricing Transparency"
  page that links the file with CMS's required filename pattern
  (`<EIN>_<name>_StandardCharges.csv`). A page-scan layer finds it.

**Reading the index (3 formats quirks)**
- **Banner text before the entries** (Houston Methodist, Memorial Hermann): a boxed
  "Instructions for viewing the price transparency files" paragraph precedes the
  `location-name:` lines. A strict parser sees no entries.
- **`location-name:Arizona General Hospital`** with no space after the colon (CommonSpirit,
  some rows). CRLF line endings everywhere.
- **Legal names**: "23330 Emergency Center, LLC d/b/a/ Elite Hospital Kingwood". Matching on
  the whole string scores 40; matching on the trade name scores 100. And "Emergency Center"
  in the legal name must not get it filtered out as a freestanding ER.

**Matching the hospital to an entry (3 hard cases)**
- **Freestanding ERs**: 24 of HCA Houston's 36 entries are "HCA HOUSTON ER 24/7 -
  <place>". They're excluded by pattern.
- **Near-duplicates**: "Baylor St Luke's Medical Center" vs "Baylor St. Luke's Medical
  Center (McNair)"; "Texas Children's Hospital" vs "... West Campus" vs "... The
  Woodlands". The base name wins when the CMS name has no qualifier, and the variants stay
  visible as candidates.
- **The CMS name is the system's, not the hospital's**: CCN 450289 is "HARRIS HEALTH"
  (address 1504 Taub Loop); the index lists "Harris Health Ben Taub Hospital" and "Harris
  Health Lyndon B Johnson Hospital". Name matching alone cannot decide; the address can.
  This is the one place a model is asked to choose, and it's given the address.
- **Missing from its own system's index**: Memorial Hermann Surgical Hospital Kingwood (a
  joint venture) is not among Memorial Hermann's 19 entries. The nearest name, "Memorial
  Hermann Sugar Land Hospital", shares only the system name. A rule that a candidate must
  share a *campus-distinctive* token turns a wrong "ambiguous" into an honest "not listed".

**The file itself (3 surprises)**
- **`.ashx` that is JSON**: Houston Methodist serves `application/octet-stream` with a
  `Content-Disposition` filename ending in `.json` and a UTF-8 BOM before the `{`. Shape is
  decided from the URL, then the download filename, then the content type, then the first
  bytes.
- **No `Content-Length` on HEAD** (CommonSpirit over HTTP/1.1); a 64-byte range GET gets
  the total from `Content-Range` instead. Nothing larger than 64 bytes is ever downloaded
  at this stage.
- **A published URL that doesn't work**: Texas Orthopedic Hospital's index points at an
  Azure blob with a SAS token whose signature is rejected (403) as published, and still
  rejected with the signature URL-encoded. HCA Kingwood's URL on the same storage account
  works. Nothing to do but report it; the trace says "file URL failed: HTTP 403".

**Currency and size**
- Townsen Memorial's file is dated **5 January 2023**. Hospitals must update at least
  annually. It is findable and parseable, and out of date; the trace will say so.
- Woodland Springs' server sends neither `Content-Length` nor a `Content-Range` for a
  range request (HTTP/2, chunked). The size stays "unknown" until the file is streamed.

**Stale reference data**
- CMS's Hospital General Information still lists "THE WOODLANDS SPECIALTY HOSPITAL"; the
  facility now operates as Woodlands Oaks Hospital under a different parent, whose site
  has the index. A renamed hospital is invisible to name-based discovery until CMS catches
  up, or until a model is asked to look for the *current* name, which is a reasonable next
  step and not done here.

## Rules this run confirmed

- **Report, never guess.** Five of fifteen end in a stated reason rather than a file. A
  system that filled those in by name similarity would have handed Memorial Hermann Sugar
  Land's prices to a Kingwood surgical hospital.
- **Match on what the hospital calls itself, not what its lawyers call it.**
- **Fuzzy matching needs a "same system, different campus" guard**, or every system index
  produces confident near-misses.
- **Shape is not the file extension.**

## The external check, and why it's weak

`hpa eval-discovery` compares each located file's domain with a dated snapshot of the
[DoltHub hospital-price-transparency](https://www.dolthub.com/repositories/dolthub/hospital-price-transparency)
`hospitals` table (163 Texas rows, publish dates 2020–2021, fetched 2026-09-18, kept in
`eval/`). Only 2 of our 15 hospitals appear in it by name: Texas Children's agrees;
HCA Kingwood differs because HCA moved its files from `kingwoodmedical.com` to an Azure
blob since 2021. So the number is **1 of 2 domains agree, and the disagreement is the
index being stale**. That is the honest state of external ground truth for this data:
there isn't a current public one, which is part of why the project exists. The per-hospital
table above, with every URL, is the evidence that can actually be checked.

## What this means for the next milestone

Extraction has to handle, on this sample alone: JSON from 63 MB to 860 MB, zip-wrapped
files, CSVs of 129 KB to 3 MB, a BOM, and files dated from 2023 to this month. It will
stream everything and record the file date next to every price.

## Addendum, milestone 3: what the files contain

*Added 2026-09-18 after extracting the 12 located files. Reproduce with `hpa scan 77030 77380 77339`
and `hpa prices "knee mri" 77030 77380 77339`.*

**11 of 12 extracted.** Townsen Memorial's "standard charges" CSV is a chargemaster export
("Charge #, Description, Dept, Rev Code, CPT/HCPCS, …, Cost, Charge Amt, Markup"), not the
CMS template: findable, dated 2023, and off-template. The other eleven are all template
v3.0.0: seven JSON, three CSV wide (two of them inside zips), one CSV tall.

**Sizes and speed.** 860 MB (HCA Kingwood, JSON) down to 129 KB (Kingwood Pines, CSV tall).
Parsing streams: the 860 MB file takes 9 s to parse and 1 s to load at a 470 MB peak; the
whole set re-extracts from disk in 39 s. The first attempt at loading rows one at a time
through DuckDB's `executemany` ran for 19 minutes before it was stopped; bulk-loading through
a temporary CSV is ~1,000× faster. HCA's blob server delivered the 860 MB at ~1 MB/s the
second time and ~15 MB/s the first: download, not parsing, is the variable cost.

**What "the price of a knee MRI" looks like in practice (CPT 73721):**

| Hospital | Cash | Gross | Negotiated min–max | Verdict |
|---|---|---|---|---|
| Harris Health (Ben Taub) | $231.94 | $3,821.00 | $208.84–$2,483.65 | unknown: no billing class |
| Houston Methodist Hospital | $1,230.00 | $2,460.00 | — | comparable (facility) |
| Houston Methodist The Woodlands | $1,243.50 | $2,487.00 | — | comparable (facility) |
| Baylor St. Luke's | $2,725.80 | $7,788.00 | $3,504.60–$7,788.00 | unknown: no billing class |
| St. Luke's Lakeside | $2,725.80 | $7,788.00 | $3,426.72–$7,788.00 | unknown: no billing class |
| St. Luke's The Woodlands | $2,725.80 | $7,788.00 | $3,348.84–$7,788.00 | unknown: no billing class |
| Elite Hospital Kingwood | $2,735.80 | $5,471.59 | $431.06–$574.74 | unknown: no billing class |
| Texas Children's | $3,174.46 | $4,738.00 | $208.84–$4,501.10 | comparable (facility, outpatient) |
| HCA Houston Kingwood | — | — | 47 lines at $215.06–$2,974.36 | modifier-specific lines only |
| Kingwood Pines, Woodland Springs (psychiatric) | — | — | — | not found |

A 14× spread in cash price for the same CPT code, and only three of nine hospitals state
the billing class that would make the comparison safe. Some of what's behind the rows:

- **Houston Methodist's cash price is exactly half of gross on every one of its 29,430 priced
  lines**: a flat 50% self-pay discount. Its negotiated min/max live on separate charge
  objects from the gross/cash ones, so the headline line shows none.
- **HCA Kingwood's cash price equals gross on every one of its 88,988 priced lines**: no
  self-pay discount anywhere in the file.
- **CommonSpirit's three files share one chargemaster** (identical gross and cash) but
  different negotiated ranges per hospital. The files have different checksums; the
  headers name three different legal entities.
- **HCA lists CPT 73721 fifty times.** Three are chargemaster lines with modifiers (bilateral,
  right, left) at gross = cash = $19,634; 47 are per-revenue-center
  lines (RC 321, 350, 612, 920, …) carrying only negotiated rates; and one "PACK INSTR
  XSMALL" has a chargemaster number `73721` of type `CDM` that merely collides with the
  CPT code (excluded by code type). HCA also writes `"modifiers": "RT"` where the JSON
  dictionary specifies a `modifier_code` array; the parser reads both.
- **Texas Children's prices the same line for inpatient and outpatient** at the same cash
  and gross but different negotiated ranges; the outpatient line is the headline and the
  inpatient one is listed.
- **Harris Health's cash price is 6% of gross.** As the county safety-net system its
  self-pay pricing is not comparable to a commercial hospital's in kind, whatever the number.
- **Colonoscopy (45378) at the Medical Center:** Methodist cash $519 (comparable), Harris
  $1,835.24 (unknown class, 5 other lines), Baylor St. Luke's negotiated rates only ($345.58–
  $7,221) with no cash or gross price, Texas Children's not found.

**Verdict vocabulary** used by `hpa prices`, in order of what it means for a reader:
`comparable` (one unmodified facility line with a price), `unknown: no billing class stated`,
`modifier-specific lines only`, `negotiated rates only`, `inpatient line only`,
`conflicting` (unmodified lines disagree), `not found`. Every line behind a verdict is one
`--all` away, with its row number or JSON path.

**Two more things extraction turned up.** Houston Methodist labels its CPT codes with code
type `HCPCS` (the CPT set is HCPCS Level I, so this is defensible, but a query filtering on
`CPT` alone would miss the whole file). Harris Health publishes prices to five decimal
places ($5,011.64785); a first schema at two decimals rounded them, and the fidelity check
caught it on the first run (254 of 256), which is what the check is for.

## Addendum, 2026-09-22: the first search outside Houston

A visitor searched an Austin ZIP. The three Ascension Seton hospitals came back "no price
file located", with the trace showing every guessed domain failing and `ascension.org`
answering 404. Ascension does publish an index, with 93 entries across its states, but at
`https://healthcare.ascension.org/cms-hpt.txt`: a subdomain that neither the hospital's
name nor the corporate domain suggests. Three things were missing, and each is now in place:

- **The seed.** Ascension is the largest Catholic system in the country and its index host
  is not guessable, so it is seeded, along with the other large Texas systems whose index
  hosts answered on 2026-09-22 (Baylor Scott & White, Methodist Health System, St. David's,
  Medical City, CHRISTUS, University Health, Parkland, Cook Children's, Children's Health,
  UTMB, JPS, UMC El Paso, UT Southwestern).
- **Following a pricing link to a sibling host.** `www.ascension.org` has no index but its
  home page links to `healthcare.ascension.org/price-transparency`. Discovery now follows a
  pricing link to another host of the same organisation and tries `cms-hpt.txt` there, so a
  system laid out this way is found without the seed and without a model.
- **The web-search fallback asked for the wrong thing.** It asked for the bare domain, so
  Claude answered `ascension.org`. It now also asks for the URL of the hospital's own page
  and tries that host first, then the apex.

Two matcher gaps showed up on the same index. CMS abbreviates ("DELL SETON MED CENTER AT
THE UNIVERSITY OF TX") where the index spells out; the matcher now reads the common
abbreviations. And sister campuses one word apart (Seton Northwest, Seton Southwest) tied
on a fuzzy score because each entry carries the system's name in parentheses; a
parenthetical that several entries share is now dropped for matching, and a word-for-word
name is a match outright. All three Seton hospitals resolve with no model call:

```
hpa locate --ccn 450867 --no-llm   # Ascension Seton Northwest
hpa locate --ccn 450056 --no-llm   # Ascension Seton Medical Center Austin
hpa locate --ccn 450124 --no-llm   # Dell Seton Medical Center at UT
```

The files themselves are zips served with a `.csv` name; the probe reads the bytes, not
the name, and the parser handles them. Seton Northwest's is 257 MB and parses to 297,292
charges in about two minutes at 403 MB peak. A failure recorded by an older discovery is
now retried rather than cached for a week, so the hosted copy looks again on its own.

Ascension's filenames carry the campus's NPI after the parent's EIN. A tie between
candidates is now settled first by looking the NPI up in the public NPI registry and
comparing the registered practice address with the CMS address (street number and city):
exactly one candidate at the hospital's address wins, a shared NPI or a silent registry
settles nothing, and only then is the model asked. Harris Health's filenames carry the EIN
only, so its tie-break still goes to the model.
