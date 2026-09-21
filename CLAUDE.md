# Working notes for this repo

Read SPEC.md first: it holds the locked decisions, the storage and caching design, and the
milestone status. README.md is the public face; its eval numbers are checked against
`eval/results.json` by `tests/test_readme_numbers.py`, so re-run `hpa eval` and update
both together.

## State (2026-09-20)

All seven milestones are done and live at https://prices.alexspi.com: hospital lookup,
live price-file discovery, streaming extraction, comparability verdicts (per hospital and
per pair), offline demo, eval harness, the first human mapping review (5 of 70 services),
the web UI (`hpa serve` + `frontend/`) and the hosted demo. 194 Python tests and 15 Vitest
tests, all offline. The deployment is one container plus Caddy on a small VM, with the
database on a mounted disk; the runbook is `docs/deploy.md` and the host's own details
(address, key, paths) stay out of the repo. Deploying = pull and `docker compose up -d
--build` on the box; the database there is refreshed with `hpa export-demo` and a copy,
with the container stopped. Live scans need the shared password in the box's `.env`.

## Layout

- `src/hpa/` — `hospitals.py` (lookup), `discovery.py` (find the file), `llm.py` (the only
  Claude calls: website search, entry tie-break, service confirmation), `mrf.py` (streaming
  parsers), `scan.py` (download + extract), `compare.py` (verdicts), `catalog.py` (the 70
  services), `pipeline.py` (a whole run; the CLI, the demo and the server share it),
  `server.py` (FastAPI + SSE), `client.py` (how the CLI finds a running server),
  `settings.py` (what a deployment allows), `export.py` (the compact hosted database),
  `evaluate.py`, `demo.py`, `cli.py`.
- `frontend/` — React + TypeScript (Vite). `trace.ts` is the reducer and holds all the
  page's state; `api.ts` the types and the three calls; `npm test` runs Vitest.
- `tests/` with real-file fixtures under `tests/fixtures/` (index files, file excerpts).
- `data/` is gitignored: `hpa.duckdb`, `raw/` reference downloads, `mrf/` price files (~2 GB).
- `demo/houston.json` (recorded run), `eval/` (results and the external index snapshot),
  `docs/` (findings write-up, mapping review sheet).

## Commands

```
hpa setup                      # reference data + geocoding, ~1 minute; rebuilds safely
hpa locate 77030 77380 77339   # discovery, cached 30 days; Claude fallbacks need .env
hpa scan 77030 77380 77339     # download + extract; files reused when validators match
hpa prices "knee mri" 77030    # verdicts from what is stored; --all for every line, --ask-claude to settle an unclear name
hpa eval | hpa demo | hpa catalog QUERY
hpa serve                      # the page + API on :8000; owns the DB file while it runs
pytest                         # no network, no key
cd frontend && npm test        # the trace reducer; npm run dev proxies /api to :8000
```

## Rules that matter here

- DuckDB allows one process on the file. `hpa scan`/`locate` write; `prices`/`eval` open
  read-only; nothing else may have it open (SPEC "Process model"). While `hpa serve` runs
  it owns the file: it leaves `data/hpa.server.json`, `prices` then goes through the API,
  and other commands raise `cli.DatabaseBusy` rather than a lock error. Go through
  `cli.open_db`, never `store.connect`, in a new command.
- Never invent a price; every number keeps its source ref. Verdicts say "unknown" rather
  than compare across missing context. A reviewed billing class is marked "(per review)".
- Claude is called only at the three fuzzy steps, may only choose among candidates the
  code produced, and every call is cached in `llm_cache` by model + per-call prompt
  version + input. When the resolver finds nothing at all, the whole 70-service list
  becomes the candidate set (live runs only, ~$0.043 a call); typos are fixed before that
  by rapidfuzz, free.
- `ANTHROPIC_API_KEY` lives in `.env` (gitignored). Never write a key into `.env.example`.
- Bump `mrf.PARSER_VERSION` when the parser's output changes; extractions are keyed by it.
- Tests use fixtures cut from real files; when a real file breaks something, add the excerpt.
- Commit messages: plain, what and why. Push to `main` is fine; CI runs pytest on 3.11/3.13.
- Findings go in `docs/houston-compliance-findings.md` with the command that reproduces them.
- A run is cache-first unless it asks to be live; only a live run touches the network,
  and only a live run may call Claude — the public endpoints are deterministic, so a
  visitor without the password can never spend money. On the CLI, `hpa prices` is
  deterministic too; `--ask-claude` is the opt-in.
  The caps live in `settings.py` and are off unless the environment sets them, so local
  behaviour never depends on them.
- The page computes nothing: verdicts and prices are `pipeline.hospital_prices` dicts, and
  a recorded run is served in the same shape as a live one. New per-hospital fields go
  there, not into the front end.
