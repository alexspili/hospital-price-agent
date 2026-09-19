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
  real but unrelated site (an apartment complex, judging by the HTML). The search found
  `woodlandspringshealth.com`, which serves a proper index. Correct.
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
