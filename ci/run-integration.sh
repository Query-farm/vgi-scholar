#!/usr/bin/env bash
# Run test/sql/*.test through DuckDB (the haybarn-unittest sqllogictest runner)
# against this worker, over one transport. Adapted from the vgi-starter
# (python) ci/run-integration.sh.
#
#   WORKER=/abs/path/to/worker-executable TRANSPORT=stdio ci/run-integration.sh
#
# Required environment:
#   WORKER            absolute path to an executable that serves the worker:
#                     no arguments = stdio; `--http --port 0` = HTTP, printing
#                     `PORT:<n>` on stdout once listening. For stdio it may also
#                     be a full command line (e.g. `docker run -i --rm IMG stdio`).
# Optional:
#   TRANSPORT         stdio | launch | http                        (default: stdio)
#   HAYBARN_UNITTEST  path to haybarn-unittest   (default: the one on PATH)
#   PYTHON            command for the mock API, may contain spaces
#                     (default: uv run --no-sync python, run from the repo root)
#   MIN_EXECUTED      fail if fewer test cases ran (default: 1)
#   EXPECTED_SKIP_REASONS  newline-separated skip reasons that are allowed,
#                     e.g. "require-env SOME_LIVE_KEY". Any other skip fails.
#   TEST_PATTERN      runner filter over the staged tree (default: test/sql/*)
#   WORKER_URL        http only: test an already-running HTTP worker (e.g. a
#                     Docker container) instead of starting $WORKER --http
#   WARMUP_TIMEOUT    seconds allowed for the extension install (default: 300)
#   KEEP_STAGE=1      keep the staged test tree for debugging
#
# The test files ATTACH `LOCATION '{VGI_SCHOLAR_WORKER}'`; this script exports that
# variable per transport.
#
# Transports:
#   stdio   DuckDB spawns the worker and talks over stdin/stdout (the default).
#   launch  DuckDB starts the worker once on an AF_UNIX socket and pools
#           connections (`LOCATION 'launch:/path'`); best for slow-starting
#           runtimes such as the JVM.
#   http    the worker runs as an HTTP server (`--http`), as in Docker deploys.
#
# Why the extra checks: the sqllogictest runner turns some errors into silent
# SKIPs (anything mentioning "HTTP" without --test-config) and exits 0 when no
# test matched. Both would make a broken lane look green, so this script passes
# a config that disables error-skipping and fails on any unexpected skip.
set -euo pipefail

TRANSPORT="${TRANSPORT:-stdio}"
if [ "$TRANSPORT" != "http" ] || [ -z "${WORKER_URL:-}" ]; then
  : "${WORKER:?absolute path to the worker executable}"
fi
HAYBARN_UNITTEST="${HAYBARN_UNITTEST:-$(command -v haybarn-unittest || true)}"
PYTHON="${PYTHON:-uv run --no-sync python}"
MIN_EXECUTED="${MIN_EXECUTED:-1}"
TEST_PATTERN="${TEST_PATTERN:-test/sql/*}"
[ -n "$HAYBARN_UNITTEST" ] || { echo "::error::haybarn-unittest not found (make tools)"; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
STAGE="$(mktemp -d)"
PIDS=()
cleanup() {
  for p in ${PIDS[@]+"${PIDS[@]}"}; do kill "$p" 2>/dev/null || true; done
  [ "${KEEP_STAGE:-0}" = "1" ] && echo "stage kept at $STAGE" || rm -rf "$STAGE"
}
trap cleanup EXIT

# start_server <log> <cmd...> — run a server that prints PORT:<n>; sets PORT.
PORT=""
start_server() {
  local log="$1"; shift
  # Create the log before backgrounding: the child opens its redirect only
  # once it is scheduled, and the poll below would otherwise read a missing
  # file, which under set -e -o pipefail kills the whole run.
  : > "$log"
  "$@" >"$log" 2>&1 &
  local pid=$!
  PIDS+=("$pid")
  for _ in $(seq 1 120); do
    kill -0 "$pid" 2>/dev/null || { echo "::error::'$*' exited early:"; cat "$log"; return 1; }
    PORT="$(sed -n 's/^PORT:\([0-9][0-9]*\).*/\1/p' "$log" | head -1)"
    [ -n "$PORT" ] && return 0
    sleep 0.5
  done
  echo "::error::'$*' never printed PORT:<n>"; cat "$log"; return 1
}

# The scholarly providers (OpenAlex / arXiv / Crossref) are redirected at a
# local mock (tests/mock_server.py), so the suite never reaches a live API. It
# prints `URL:<base>` once bound; the base URLs are exported, so every
# transport's worker inherits them.
MOCK_LOG="$STAGE/mock.log"
: > "$MOCK_LOG"
# shellcheck disable=SC2086
(cd "$REPO" && exec $PYTHON -m tests.mock_server) >"$MOCK_LOG" 2>&1 &
mock_pid=$!
PIDS+=("$mock_pid")
BASE=""
for _ in $(seq 1 120); do
  kill -0 "$mock_pid" 2>/dev/null || { echo "::error::the mock provider server exited early:"; cat "$MOCK_LOG"; exit 1; }
  BASE="$(sed -n 's/^URL:\(.*\)$/\1/p' "$MOCK_LOG" | head -1)"
  [ -n "$BASE" ] && break
  sleep 0.5
done
[ -n "$BASE" ] || { echo "::error::the mock provider server never printed URL:<base>"; cat "$MOCK_LOG"; exit 1; }
export VGI_SCHOLAR_OPENALEX_BASE_URL="$BASE"
export VGI_SCHOLAR_ARXIV_BASE_URL="$BASE"
export VGI_SCHOLAR_CROSSREF_BASE_URL="$BASE"

HTTP=0
[ "$TRANSPORT" = "http" ] && HTTP=1

# Stage the tests, rewriting `require vgi` into a signed INSTALL + LOAD (the
# standalone runner links no extensions) and loading httpfs for HTTP workers.
# These tests LOAD vgi themselves (haybarn skips `require vgi`), so httpfs is
# also loaded after each bare `LOAD vgi;`.
mkdir -p "$STAGE/test/sql"
for f in "$REPO"/test/sql/*.test; do
  awk -v http="$HTTP" '
    /^require[ \t]+vgi[ \t]*$/ {
      print "statement ok"; print "LOAD vgi;"; print ""
      if (http == 1) { print "statement ok"; print "LOAD httpfs;"; print "" }
      next
    }
    /^LOAD[ \t]+vgi[ \t]*;[ \t]*$/ && http == 1 {
      print; print ""; print "statement ok"; print "LOAD httpfs;"
      next
    }
    { print }' "$f" > "$STAGE/test/sql/$(basename "$f")"
done

# Workers resolve relative paths against the runner's directory (stdio and
# launch inherit it), so the HTTP worker is started there too.
cd "$STAGE"

WORKER_PID=""
case "$TRANSPORT" in
  stdio)  export VGI_SCHOLAR_WORKER="$WORKER" ;;
  launch) export VGI_SCHOLAR_WORKER="launch:$WORKER" ;;
  http)
    if [ -n "${WORKER_URL:-}" ]; then
      export VGI_SCHOLAR_WORKER="$WORKER_URL"
    else
      start_server "$STAGE/worker.log" "$WORKER" --http --port 0
      WORKER_PID="${PIDS[${#PIDS[@]}-1]}"
      export VGI_SCHOLAR_WORKER="http://127.0.0.1:$PORT"
    fi
    ;;
  *) echo "::error::unknown TRANSPORT=$TRANSPORT (expected stdio|launch|http)"; exit 1 ;;
esac

# Install the extensions once, refreshing any stale cached copy of vgi.
cat > "$STAGE/test/_warm.test" <<'EOT'
statement ok
FORCE INSTALL vgi FROM community;

statement ok
INSTALL httpfs FROM core;

statement ok
INSTALL json FROM core;
EOT
# Bounded: a stalled extension download would otherwise hang the lane until the
# job timeout. WARMUP_TIMEOUT is in seconds.
"$HAYBARN_UNITTEST" --keep-home --test-dir "$STAGE" "test/_warm.test" >/dev/null 2>&1 &
warm_pid=$!
warm_deadline=$((SECONDS + ${WARMUP_TIMEOUT:-300}))
while kill -0 "$warm_pid" 2>/dev/null && [ "$SECONDS" -lt "$warm_deadline" ]; do sleep 1; done
if kill -0 "$warm_pid" 2>/dev/null; then
  kill "$warm_pid" 2>/dev/null || true
  wait "$warm_pid" 2>/dev/null || true
  echo "::warning::extension warm-up timed out after ${WARMUP_TIMEOUT:-300}s (stalled download?)"
elif ! wait "$warm_pid"; then
  echo "::warning::extension warm-up did not fully succeed"
fi
rm -f "$STAGE/test/_warm.test"

cat > "$STAGE/no_error_skip.json" <<'EOT'
{"skip_error_messages": ["__vgi_starter_never_matches__"]}
EOT

echo "Running $TEST_PATTERN over $TRANSPORT (worker: $VGI_SCHOLAR_WORKER)"
LOG="$STAGE/unittest.log"
rc=0
( cd "$STAGE" && "$HAYBARN_UNITTEST" --keep-home --test-dir "$STAGE" \
    --test-config "$STAGE/no_error_skip.json" "$TEST_PATTERN" ) 2>&1 | tee "$LOG" && rc=0 || rc="${PIPESTATUS[0]}"

if grep -q 'No test cases matched\|No tests ran' "$LOG"; then
  echo "::error::no test cases matched; the staging is wrong"; exit 1
fi
total="$(sed -n 's/^\[[0-9]*\/\([0-9]*\)\].*/\1/p' "$LOG" | tail -1)"
total="${total:-0}"
skips="$(awk '/^Skipped tests for the following reasons:/{b=1;next} b&&/^[[:space:]]*$/{b=0} b&&match($0,/: [0-9]+[[:space:]]*$/){print substr($0,1,RSTART-1) "\t" substr($0,RSTART+2)+0}' "$LOG")"
skipped=0
while IFS=$'\t' read -r reason n; do
  [ -n "$reason" ] || continue
  skipped=$((skipped + n))
  if ! printf '%s\n' "${EXPECTED_SKIP_REASONS:-}" | grep -qxF "$reason"; then
    echo "::error::unexpected skip: '$reason'. A test file silently stopped running;" \
         "fix the gate or add it to EXPECTED_SKIP_REASONS."
    rc=1
  fi
done <<< "$skips"
executed=$((total - skipped))
echo "executed $executed of $total test files over $TRANSPORT ($skipped skipped)"
if [ "$executed" -lt "$MIN_EXECUTED" ]; then
  echo "::error::only $executed test files ran (MIN_EXECUTED=$MIN_EXECUTED)"; rc=1
fi
if [ -n "$WORKER_PID" ] && ! kill -0 "$WORKER_PID" 2>/dev/null; then
  echo "::error::the HTTP worker died during the run:"; cat "$STAGE/worker.log"; rc=1
fi
exit "$rc"
