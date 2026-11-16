# vgi-scholar worker -- dev and test targets. `make help` lists them.
#
#   make test        # unit (pytest) + SQL end-to-end over stdio, launch and http
#   make test-unit   # pytest only (fixture parsers + mock-server E2E, no live network)
#   make test-sql    # test/sql/*.test through DuckDB via ci/run-integration.sh
#   make lint        # ruff
#   make typecheck   # mypy
#
# ci/run-integration.sh points the worker's providers at a local mock HTTP server
# (tests/mock_server.py) via the VGI_SCHOLAR_*_BASE_URL env vars, so NOTHING in
# the CI gate touches a live external API. haybarn 2.0 is required: its
# community `vgi` extension speaks the worker's VGI protocol (vgi.v3 / 3.3).

HAYBARN_VERSION  ?= 2.0.0rc11
WORKER           := $(CURDIR)/.venv/bin/vgi-scholar-worker
TOOLS            := $(CURDIR)/.tools
HAYBARN_UNITTEST := $(TOOLS)/bin/haybarn-unittest
TRANSPORTS       ?= stdio launch http

build: ## Install the worker (all extras: HTTP serving needs `http`) into .venv
	uv sync --locked --all-extras

tools: ## Install the pinned SQL test runner into .tools
	@test -x $(HAYBARN_UNITTEST) || { uv venv -q $(TOOLS) && uv pip install -q -p $(TOOLS) haybarn-unittest==$(HAYBARN_VERSION); }

test-sql: build tools ## SQL tests through DuckDB over each transport: make test-sql TRANSPORTS=launch
	@set -e; for t in $(TRANSPORTS); do \
	  WORKER=$(WORKER) HAYBARN_UNITTEST=$(HAYBARN_UNITTEST) TRANSPORT=$$t ci/run-integration.sh; \
	done

test-sql-all: test-sql ## Alias: SQL tests over every transport

.DEFAULT_GOAL := help
.PHONY: help build tools test test-unit test-sql test-sql-all pytest lint typecheck check

help: ## List the targets
	@awk 'BEGIN{FS=":.*## "} /^[a-zA-Z_-]+:.*## /{printf "  %-14s %s\n",$$1,$$2}' $(MAKEFILE_LIST)

test: test-unit test-sql ## Unit + SQL tests

check: lint typecheck test ## Lint, types, unit + SQL tests

test-unit: pytest ## Unit tests (pytest)

pytest: build
	uv run --no-sync pytest -q

lint: ## ruff
	uv run --no-sync ruff check .

typecheck: ## mypy
	uv run --no-sync mypy vgi_scholar
