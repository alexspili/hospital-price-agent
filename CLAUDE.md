# Working notes for this repo

Read SPEC.md first: it holds the locked decisions, the storage and caching design, and the
milestone status. README.md is the public face; keep its numbers generated, not typed.

## State (2026-09-19)

Milestones 1–5 are done and pushed: hospital lookup, live price-file discovery, streaming
extraction, comparability verdicts, offline demo, eval harness, and the first human mapping
review (5 of 70 services). 120 tests, all offline. Next is milestone 6: a FastAPI backend
with an SSE trace endpoint and a small React + TypeScript (Vite) front end in `frontend/`,
split pane with the trace on the left and results on the right. Then milestone 7, the
hosted demo (cache-first on pre-scanned Houston ZIPs).

## Layout

- `src/hpa/` — `hospitals.py` (lookup), `discovery.py` (find the file), `llm.py` (the only
  Claude calls: website search, entry tie-break, service confirmation), `mrf.py` (streaming
  parsers), `scan.py` (download + extract), `compare.py` (verdicts), `catalog.py` (the 70
  services), `evaluate.py`, `demo.py`, `cli.py`.
- `tests/` with real-file fixtures under `tests/fixtures/` (index files, file excerpts).
- `data/` is gitignored: `hpa.duckdb`, `raw/` reference downloads, `mrf/` price files (~2 GB).
- `demo/houston.json` (recorded run), `eval/` (results and the external index snapshot),
  `docs/` (findings write-up, mapping review sheet).

## Commands

```
hpa setup                      # reference data + geocoding, ~1 minute; rebuilds safely
hpa locate 77030 77380 77339   # discovery, cached 30 days; Claude fallbacks need .env
hpa scan 77030 77380 77339     # download + extract; files reused when validators match
hpa prices "knee mri" 77030    # verdicts; --all for every line
hpa eval | hpa demo | hpa catalog QUERY
pytest                         # no network, no key
```

## Rules that matter here

- DuckDB allows one process on the file. `hpa scan`/`locate` write; `prices`/`eval` open
  read-only; nothing else may have it open, including a running server (SPEC "Process model").
- Never invent a price; every number keeps its source ref. Verdicts say "unknown" rather
  than compare across missing context. A reviewed billing class is marked "(per review)".
- Claude is called only at the three fuzzy steps, may only choose among candidates the
  code produced, and every call is cached in `llm_cache` by model + prompt version + input.
- `ANTHROPIC_API_KEY` lives in `.env` (gitignored). Never write a key into `.env.example`.
- Bump `mrf.PARSER_VERSION` when the parser's output changes; extractions are keyed by it.
- Tests use fixtures cut from real files; when a real file breaks something, add the excerpt.
- Commit messages: plain, what and why. Push to `main` is fine; CI runs pytest on 3.11/3.13.
- Findings go in `docs/houston-compliance-findings.md` with the command that reproduces them.
