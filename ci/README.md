# CI: the vgi-scholar SQL suite

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs `test/sql/*.test`
through the **real DuckDB `vgi` extension** with
[`run-integration.sh`](run-integration.sh), the vgi-starter's standard harness.
`make test-sql` runs the same script locally over all three transports.

## How it works

- The published `haybarn-unittest` sqllogictest runner (pinned by
  `HAYBARN_VERSION`) runs the tests; the signed `vgi` extension is installed with
  `FORCE INSTALL vgi FROM community` (plus `httpfs` and `json` from core).
- The tests are staged into a temp dir: `require vgi` becomes `LOAD vgi`, and
  on the http transport `LOAD httpfs` is added after each `LOAD vgi;`.
- The tests ATTACH `LOCATION '{VGI_SCHOLAR_WORKER}'`; the script exports that variable
  per transport.
- Guards: error-skipping is disabled with a test config, any skip not listed in
  `EXPECTED_SKIP_REASONS` fails the run, and fewer than `MIN_EXECUTED` executed
  test files fails it too.

## Transports

| `TRANSPORT` | `VGI_SCHOLAR_WORKER`                    | How the worker is reached                                |
| ----------- | -------------------------- | -------------------------------------------------------- |
| `stdio`     | `$WORKER`                  | DuckDB spawns the worker per connection (stdin/stdout)   |
| `launch`    | `launch:$WORKER`           | DuckDB starts it once on an AF_UNIX socket and pools it  |
| `http`      | `http://127.0.0.1:<port>`  | the script starts `$WORKER --http --port 0`              |

`WORKER` is the console script `.venv/bin/vgi-scholar-worker` (`uv sync --locked
--all-extras`; the `http` extra provides the HTTP server).

## Repo-specific

The script starts the mock provider server (`tests/mock_server.py`) first and
exports `VGI_SCHOLAR_{OPENALEX,ARXIV,CROSSREF}_BASE_URL`, so every transport's
worker talks to it and nothing reaches a live API.

## Run it locally

```bash
make test-sql                       # stdio, launch and http
make test-sql TRANSPORTS=launch     # one transport
```
