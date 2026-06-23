# CLAUDE.md — vgi-scholar

Guidance for working in this repo. vgi-scholar is a **VGI worker** (Python) that
searches scholarly literature from DuckDB/SQL across free, ToS-clean providers
(OpenAlex, arXiv, Crossref) behind one pluggable surface, normalized into a
single unified schema.

## What this is

- A VGI worker built on the `vgi-python` SDK. It is launched by DuckDB (`ATTACH
  ... (TYPE vgi, LOCATION '...')`) as a stdio subprocess, or over HTTP via
  `serve.py`.
- The SQL surface is two **table functions** (`scholar_search`,
  `scholar_providers`) in the `scholar` catalog assembled in `scholar_worker.py`.

## VGI conventions that matter here

- **Table functions take `name := value` named args; scalar functions are
  positional-only.** Both public functions here are table functions, so
  `provider :=`, `count :=`, `page_size :=` work. There are no scalar functions.
- **LIST / TIMESTAMPTZ / JSON returns REQUIRE explicit `arrow_type`.** The unified
  schema pins them in `schema_utils.py`: `authors` is `LIST<VARCHAR>`,
  `published` is `TIMESTAMPTZ` (`pa.timestamp("us", tz="UTC")`), `extra` is a
  VARCHAR tagged as JSON.
- **Scan state must be serializable.** `scholar_search` is a
  `TableFunctionGenerator[ScholarSearchArgs, _ScanState]`; `_ScanState` extends
  `ArrowSerializableDataclass` so the framework round-trips the pagination cursor
  across `process()` ticks (and across HTTP requests). Each tick fetches one
  provider page, emits it, advances `state.cursor`, and finishes when `count` is
  satisfied or the provider runs out.
- **Never crash the worker on a provider error.** `http_client.get` raises
  `ProviderError` (with a timeout + bounded 429/5xx retry); `process()` converts
  it into a clean `RuntimeError` → DuckDB error.

## Adding a provider

1. Add `vgi_scholar/providers/<name>.py` with a class whose `search(query,
   count, cursor, opts) -> Page` maps the API response to `Result`s + a
   `next_cursor`. Take `base_url` in `__init__` (so tests can redirect it).
2. Register it in `vgi_scholar/providers/__init__.py` `_FACTORIES`.
3. Add a fixture (`tests/fixtures/<name>.*`) + a parser test in
   `tests/test_providers.py`, and add the name to `PROVIDERS` in
   `tests/test_mock_e2e.py` and `scripts/run_sql_e2e.py`; teach `tests/mock_server.py`
   to serve its shape.

## Testing (NO live external API in the CI gate)

- `make test-unit` / `pytest` — fixture parser tests (`test_providers.py`) +
  mock-server E2E (`test_mock_e2e.py`). The mock (`tests/mock_server.py`) serves
  canned, *paged* responses in-process.
- `make test-sql` — the real worker subprocess under DuckDB via
  `haybarn-unittest`, with providers redirected at the mock server by
  `scripts/run_sql_e2e.py`. The `.test` file uses `LOAD vgi;` (NEVER `require
  vgi`), `require-env VGI_SCHOLAR_WORKER`, and ATTACHes `${VGI_SCHOLAR_WORKER}`.
- `make lint` (ruff) and `make typecheck` (mypy `vgi_scholar`) must be clean.
- Live smoke (`tests/test_live_smoke.py`) is GATED by `VGI_SCHOLAR_LIVE=1` and is
  not in the CI gate.

When changing pagination or the unified schema, re-run BOTH `make test-unit` and
`make test-sql` — the scan-state round-trip is asserted in both.

## Polite-pool norms

OpenAlex and Crossref reward clients that identify with a contact e-mail. The
worker always sends a descriptive `User-Agent`; set `VGI_SCHOLAR_MAILTO` to also
send `mailto`. Respect each API's rate limits.

## Licensing

Worker code is MIT (`LICENSE`). Providers are accessed over plain HTTP; each is
free and ToS-clean for metadata search. See README "Licensing".
