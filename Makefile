# vgi-scholar worker -- dev and test targets.
#
# Usage:
#   make test        # unit (pytest) + SQL end-to-end (haybarn-unittest, mock server)
#   make test-unit   # pytest only (fixture parsers + mock-server E2E, no live network)
#   make test-sql    # SQL end-to-end only (haybarn glob, driven against a mock server)
#   make lint        # ruff
#   make typecheck   # mypy
#
# The SQL suite drives the worker as a real subprocess over stdio: haybarn-unittest
# ATTACHes `${VGI_SCHOLAR_WORKER}`, then runs the .test files in test/sql/. The
# worker's providers are pointed at a local mock HTTP server (started by the test
# harness) via the VGI_SCHOLAR_*_BASE_URL env vars, so NOTHING in the CI gate
# touches a live external API.

# Worker stdio command (overridable). Use the synced project venv python so the
# worker runs the LOCKED vgi-python (`uv sync`), NOT the PEP-723 inline-script env
# `uv run` would resolve — that env caches a stale SDK and can drift from the lock.
WORKER_STDIO   ?= $(CURDIR)/.venv/bin/python $(CURDIR)/scholar_worker.py

# haybarn-unittest: the DuckDB sqllogictest runner (uv tool install haybarn-unittest).
HAYBARN        ?= haybarn-unittest
TEST_DIR        = .
TEST_PATTERN    = test/sql/*

.PHONY: test test-unit test-sql pytest lint typecheck

test: test-unit test-sql

test-unit: pytest

pytest:
	uv run --no-sync pytest -q

# End-to-end SQL: start the mock provider server, export its URL into the
# per-provider base-URL env vars, then run the haybarn glob with the worker
# command exported. A tiny Python launcher keeps the server alive only for the
# duration of the run and tears it down afterward.
test-sql:
	@command -v $(HAYBARN) >/dev/null 2>&1 || { \
		echo "ERROR: $(HAYBARN) not found. Install it with:" >&2; \
		echo "  uv tool install haybarn-unittest" >&2; \
		echo "  (then ensure ~/.local/bin is on PATH)" >&2; \
		exit 1; \
	}
	VGI_SCHOLAR_WORKER="$(WORKER_STDIO)" \
	HAYBARN="$(HAYBARN)" TEST_DIR="$(TEST_DIR)" TEST_PATTERN="$(TEST_PATTERN)" \
		uv run --no-sync python scripts/run_sql_e2e.py

lint:
	uv run --no-sync ruff check .

typecheck:
	uv run --no-sync mypy vgi_scholar
