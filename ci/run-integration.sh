#!/usr/bin/env bash
# Copyright 2026 Query Farm LLC - https://query.farm
#
# Run this repo's sqllogictest suite (test/sql/*.test) against the vgi-scholar
# VGI worker, using a prebuilt standalone `haybarn-unittest` and the signed
# community `vgi` extension — no C++ build from source. See ci/README.md.
#
# The scholarly providers (OpenAlex / arXiv / Crossref) are redirected at a
# local in-process mock HTTP server (tests/mock_server.py) via the
# VGI_SCHOLAR_<PROVIDER>_BASE_URL env vars, so the suite is deterministic and
# never egresses to a live API.
#
# Required environment:
#   HAYBARN_UNITTEST    path to the haybarn-unittest binary
#   VGI_SCHOLAR_WORKER  worker LOCATION the .test files ATTACH (a stdio command)
# Optional:
#   STAGE               scratch dir for the preprocessed test tree (default: mktemp)
set -euo pipefail

: "${HAYBARN_UNITTEST:?path to the haybarn-unittest binary}"
: "${VGI_SCHOLAR_WORKER:?worker LOCATION (stdio command or http:// URL)}"

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
STAGE="${STAGE:-$(mktemp -d)}"

echo "Staging preprocessed tests into $STAGE ..."
mkdir -p "$STAGE/test/sql"
for f in "$REPO"/test/sql/*.test; do
  awk -f "$HERE/preprocess-require.awk" "$f" > "$STAGE/test/sql/$(basename "$f")"
done

# Start the in-process mock provider server (from the repo root so
# `tests.mock_server` imports). It prints `URL:<base>` once bound and then
# blocks; we read the URL, redirect every provider at it, and kill it on exit.
MOCK_OUT="$(mktemp)"
( cd "$REPO" && uv run --no-sync python - >"$MOCK_OUT" 2>/dev/null <<'PY' ) &
import sys, time
from tests.mock_server import MockServer
srv = MockServer()
srv.__enter__()
print(f"URL:{srv.base_url}", flush=True)
try:
    while True:
        time.sleep(3600)
finally:
    srv.__exit__(None, None, None)
PY
MOCK_PID=$!
cleanup() { kill "$MOCK_PID" 2>/dev/null || true; rm -f "$MOCK_OUT"; }
trap cleanup EXIT

BASE=""
for _ in $(seq 1 100); do
  BASE="$(sed -n 's/^URL:\(.*\)$/\1/p' "$MOCK_OUT" | head -n1)"
  [ -n "$BASE" ] && break
  sleep 0.1
done
if [ -z "$BASE" ]; then
  echo "ERROR: mock provider server did not report a URL" >&2
  exit 1
fi
echo "Mock provider server at $BASE"
export VGI_SCHOLAR_OPENALEX_BASE_URL="$BASE"
export VGI_SCHOLAR_ARXIV_BASE_URL="$BASE"
export VGI_SCHOLAR_CROSSREF_BASE_URL="$BASE"

cd "$STAGE"

# Warm the extension cache once: vgi from the signed community channel. A miss
# here is only a warning — the per-test INSTALL/LOAD (injected by
# preprocess-require.awk) is what actually gates each file.
echo "Warming the extension cache (vgi from community) ..."
mkdir -p "$STAGE/test"
cat > "$STAGE/test/_warm.test" <<'EOF'
# name: test/_warm.test
# group: [warm]
statement ok
INSTALL vgi FROM community;
EOF
"$HAYBARN_UNITTEST" "test/_warm.test" >/dev/null 2>&1 || echo "::warning::extension warm step did not fully succeed"
rm -f "$STAGE/test/_warm.test"

# Run the whole suite in one invocation, streaming the runner's native
# sqllogictest report. Any failed assertion exits non-zero and fails the job.
echo "Running suite (worker: $VGI_SCHOLAR_WORKER) ..."
"$HAYBARN_UNITTEST" "test/sql/*"
