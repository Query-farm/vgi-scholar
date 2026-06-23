# CI: the vgi-calendar worker integration suite

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs the unit tests
and this repo's sqllogictest suite (`test/sql/*.test`) against the vgi-calendar
VGI worker through the **real DuckDB `vgi` extension** on every push / PR.

## How it works (no C++ build)

Rather than building the vgi DuckDB extension from source, CI drives a
**prebuilt** standalone `haybarn-unittest` (the DuckDB/Haybarn sqllogictest
runner, published in Haybarn's releases) and installs the **signed** `vgi`
extension from the Haybarn community channel:

1. **Install the worker** — `uv sync --frozen` into a venv. `calendar_worker.py`
   is a self-contained PEP 723 stdio worker the extension can spawn via
   `uv run calendar_worker.py`.
2. **Download the runner** — the matching `haybarn_unittest-*` asset per
   platform from the latest Haybarn release.
3. **Preprocess** — the standalone runner links none of the extensions the
   tests gate on, so [`preprocess-require.awk`](preprocess-require.awk) rewrites
   each `require <ext>` into an explicit signed `INSTALL <ext> FROM
   {community,core}; LOAD <ext>;`. These tests skip `require vgi` (haybarn
   silently SKIPs it) and `LOAD vgi;` directly, so the awk also injects an
   `INSTALL vgi FROM community;` right before each bare `LOAD vgi;`. `require-env`
   and everything else pass through untouched.
4. **Run** — [`run-integration.sh`](run-integration.sh) stages the preprocessed
   tree, points `VGI_CALENDAR_WORKER` at `uv run calendar_worker.py`, warms the
   extension cache once, then runs the suite in a single `haybarn-unittest`
   invocation. Any failed assertion exits non-zero and fails the job.

## Run it locally

```bash
uv sync --python 3.13                       # install the worker + deps
# point HAYBARN_UNITTEST at a haybarn-unittest binary (or a local DuckDB
# `unittest` built with the vgi extension), and the worker at the stdio command:
HAYBARN_UNITTEST=/path/to/haybarn-unittest \
VGI_CALENDAR_WORKER="uv run --python 3.13 calendar_worker.py" \
  ci/run-integration.sh
```

Or use the Makefile target `make test-sql`, which installs `haybarn-unittest`
as a uv tool and points the worker at `uv run --python 3.13 calendar_worker.py`.
