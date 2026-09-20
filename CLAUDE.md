# Working notes for this repo

Read SPEC.md first: it holds the locked decisions, the storage and caching design, and the
milestone status. README.md is the public face; keep its numbers generated, not typed.

## State (2026-09-19)

Milestones 1–6 are done and pushed: hospital lookup, live price-file discovery, streaming
extraction, comparability verdicts, offline demo, eval harness, the first human mapping
review (5 of 70 services), and the web UI (`hpa serve` + `frontend/`). 146 Python tests
and 11 Vitest tests, all offline. Milestone 7 is live at https://prices.alexspi.com
(Lightsail 2 GB Debian, us-east-2, instance `hpa-prices-2`, static IP 3.129.225.38, DNS at
Porkbun). Deploying = ssh admin@the IP with ~/.ssh/hpa-prices.pem, `cd ~/hpa && git pull &&
sudo docker compose up -d --build`. The database lives at /mnt/hpa/hpa.duckdb, refreshed
with `hpa export-demo` and scp. Settings are in ~/hpa/.env (PIN, caps); no API key there
yet. All seven milestones are done.

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
hpa prices "knee mri" 77030    # verdicts; --all for every line
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
  code produced, and every call is cached in `llm_cache` by model + prompt version + input.
- `ANTHROPIC_API_KEY` lives in `.env` (gitignored). Never write a key into `.env.example`.
- Bump `mrf.PARSER_VERSION` when the parser's output changes; extractions are keyed by it.
- Tests use fixtures cut from real files; when a real file breaks something, add the excerpt.
- Commit messages: plain, what and why. Push to `main` is fine; CI runs pytest on 3.11/3.13.
- Findings go in `docs/houston-compliance-findings.md` with the command that reproduces them.
- A run is cache-first unless it asks to be live; only a live run touches the network,
  and only a live run may call Claude — the public endpoints are deterministic, so a
  visitor with no PIN can never spend money.
  The caps live in `settings.py` and are off unless the environment sets them, so local
  behaviour never depends on them.
- The page computes nothing: verdicts and prices are `pipeline.hospital_prices` dicts, and
  a recorded run is served in the same shape as a live one. New per-hospital fields go
  there, not into the front end.
