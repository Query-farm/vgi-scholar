# CI: the vgi-scholar worker integration suite

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs the unit tests
and this repo's sqllogictest suite (`test/sql/*.test`) against the vgi-scholar
VGI worker through the **real DuckDB `vgi` extension** on every push / PR.

## How it works (no C++ build)

Rather than building the vgi DuckDB extension from source, CI drives a
**prebuilt** standalone `haybarn-unittest` (the DuckDB/Haybarn sqllogictest
runner, published in Haybarn's releases) and installs the **signed** `vgi`
extension from the Haybarn community channel:

1. **Install the worker** — `uv sync --frozen --extra http` into a venv.
   `scholar_worker.py` is a self-contained PEP 723 stdio worker the extension
   can spawn via `uv run scholar_worker.py`.
2. **Download the runner** — the matching `haybarn_unittest-*` asset per platform.
3. **Preprocess** — [`preprocess-require.awk`](preprocess-require.awk) rewrites
   each `require <ext>` into an explicit signed `INSTALL <ext> FROM
   {community,core}; LOAD <ext>;`, and injects `INSTALL vgi FROM community;`
   before each bare `LOAD vgi;` (these tests skip `require vgi`, which haybarn
   silently SKIPs, and `LOAD vgi;` directly). `require-env` and everything else
   pass through untouched.
4. **Run** — [`run-integration.sh`](run-integration.sh) stages the preprocessed
   tree, starts the mock provider server, resolves `VGI_SCHOLAR_WORKER` (the
   ATTACH `LOCATION`) per `$TRANSPORT`, warms the extension cache once, then runs
   the suite in a single `haybarn-unittest` invocation. Any failed assertion
   fails the job.

## The mock-driven worker (all transports)

The scholarly providers (OpenAlex / arXiv / Crossref) are redirected at a local
in-process canned-response mock HTTP server ([`tests/mock_server.py`](../tests/mock_server.py))
via the `VGI_SCHOLAR_<PROVIDER>_BASE_URL` env vars, so the authoritative SQL
suite drives the real worker end to end against deterministic, *paged* fixtures —
no keys, no cost, no live network egress.

`run-integration.sh` starts that mock server **once, out of band** (`python -m
tests.mock_server`, which prints `URL:<base>` and blocks), reads the URL, and
`export`s the three `VGI_SCHOLAR_*_BASE_URL` vars. Because they are exported,
**the same mock server serves every transport** — the worker reads them whether
DuckDB reaches it over stdio, HTTP, or an AF_UNIX socket, and for the
out-of-band legs the booted worker inherits them from the environment. The mock
server stays alive for the life of the run and is trap-killed on exit (a single
`cleanup()` kills both the mock server and, for http/unix, the worker).

## Transport matrix (subprocess | http | unix)

The same `test/sql/*.test` suite is run over all three VGI transports — the
extension picks the transport from the `LOCATION` string the `.test` files
`ATTACH`, and `run-integration.sh` builds that string from `$TRANSPORT`:

| `TRANSPORT`  | `VGI_SCHOLAR_WORKER` (LOCATION)             | How the worker is reached |
|--------------|---------------------------------------------|---------------------------|
| `subprocess` | `.venv/bin/python scholar_worker.py`        | extension spawns the worker per query; Arrow IPC over stdin/stdout (default) |
| `http`       | `http://127.0.0.1:<port>`                   | harness boots `scholar_worker.py --http --port 0 --port-file <f>`, waits for the port-file, then ATTACHes that URL |
| `unix`       | `unix:///tmp/scholar-<pid>.sock`            | harness boots `scholar_worker.py --unix <sock>`, waits for the socket, then ATTACHes it |

The CI `integration` job is a `transport: [subprocess, http, unix]` × `os:
[ubuntu-latest, macos-latest]` matrix; each leg runs `ci/run-integration.sh` with
`TRANSPORT=<t>`. Run a single transport locally with e.g.
`TRANSPORT=http ci/run-integration.sh`.

### Port / socket discovery

- **http**: the worker writes its auto-selected port to `--port-file` atomically,
  so the harness watches for that file (not stdout). Boot line:
  `scholar_worker.py --http --port 0 --port-file <f>`.
- **unix**: the worker binds the socket and prints `UNIX:<abs-path>`; the harness
  polls for the socket file (`test -S`). Boot line:
  `scholar_worker.py --unix <sock>`.

Both out-of-band server processes run with cwd = the repo root (so the worker
resolves the `vgi_scholar` package and inherits the exported `*_BASE_URL` vars).

### HTTP transport needs the `httpfs` extension (resolved, not gated)

The vgi extension implements HTTP transport on top of DuckDB's **httpfs**
extension, so an `http://` ATTACH binds with `VGI HTTP transport requires the
httpfs extension` unless httpfs is loaded first. This is a **dependency**, not a
protocol limitation, so we resolve it: the http leg injects a signed `INSTALL
httpfs FROM core; LOAD httpfs;` into each staged `.test` (after the awk-injected
`LOAD vgi;`). The leg also needs the worker's `http` extra (waitress) —
`pyproject.toml` ships an `http` extra (`vgi-python[http]`), the PEP 723 header
in `scholar_worker.py` lists `vgi-python[http]`, and CI runs `uv sync --frozen
--extra http`.

> **Sharp edge — the runner silently SKIPs HTTP errors.** The haybarn/DuckDB
> sqllogictest runner's default skip list skips any statement whose error
> contains `"HTTP"` or `"Unable to connect"`, so a broken http setup reports
> "All tests were skipped" — a green-looking **fake pass**.
> `run-integration.sh` fails the leg unless the runner reports `All tests passed
> (N assertions …)` with N > 0 and zero skips.

### `scholar_search` pagination over HTTP (externalized cursor — no gate)

`scholar_search` is a streaming/paging table function: it fetches one provider
page per `process()` tick and emits it across multiple ticks until `count` is
satisfied. Streaming table functions run fine over the **stateless** HTTP
transport **because the cursor is externalized**: the per-scan position lives in
a plain-serializable `_ScanState(ArrowSerializableDataclass)` (`cursor` /
`emitted` / `started` / `done`) that the framework round-trips through its
continuation token on every tick (and so across independent HTTP requests). The
mock returns one result per page, so `count := 5, page_size := 1` forces five
paged ticks; the http leg runs the **full** suite including that scan-state
round-trip (contiguous unique titles 0..4) — nothing is gated. (This is the same
"externalize the scan position into the serialized state" pattern as the vgi-cve
cursor fix.)

### Per-transport status

- **subprocess**: GREEN — 33 assertions.
- **http**: GREEN — 35 assertions (33 + the injected httpfs INSTALL/LOAD). Full
  suite incl. the `scholar_search` paging round-trip.
- **unix**: GREEN — 33 assertions.

## Run it locally

```bash
uv sync --python 3.13 --extra http
HAYBARN_UNITTEST=/path/to/haybarn-unittest \
WORKER_CMD="$PWD/.venv/bin/python $PWD/scholar_worker.py" \
  TRANSPORT=subprocess ci/run-integration.sh    # or TRANSPORT=http / TRANSPORT=unix
```

`TRANSPORT` defaults to `subprocess`, and `WORKER_CMD` defaults to
`uv run --python 3.13 <repo>/scholar_worker.py`. Or use the Makefile target
`make test-sql` (subprocess, via `scripts/run_sql_e2e.py`).
