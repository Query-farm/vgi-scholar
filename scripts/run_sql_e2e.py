"""Run the haybarn SQL E2E suite against the local mock provider server.

Starts :class:`tests.mock_server.MockServer`, exports its URL into every
``VGI_SCHOLAR_<PROVIDER>_BASE_URL`` env var (so the worker's providers hit the
mock instead of a live API), then runs the haybarn-unittest glob with the worker
command in ``VGI_SCHOLAR_WORKER``. Nothing here touches a live external API.

Driven by the Makefile ``test-sql`` target; reads:
    VGI_SCHOLAR_WORKER  worker stdio command (required)
    HAYBARN             runner binary (default: haybarn-unittest)
    TEST_DIR            haybarn --test-dir (default: .)
    TEST_PATTERN        haybarn glob (default: test/sql/*)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Ensure the repo root is importable so `tests.mock_server` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.mock_server import MockServer  # noqa: E402

PROVIDERS = ["openalex", "arxiv", "crossref"]


def main() -> int:
    """Run the SQL E2E suite against the worker with providers mocked locally."""
    worker = os.environ.get("VGI_SCHOLAR_WORKER")
    if not worker:
        print("ERROR: VGI_SCHOLAR_WORKER is not set", file=sys.stderr)
        return 2

    haybarn = os.environ.get("HAYBARN", "haybarn-unittest")
    test_dir = os.environ.get("TEST_DIR", ".")
    pattern = os.environ.get("TEST_PATTERN", "test/sql/*")

    with MockServer() as server:
        env = dict(os.environ)
        for name in PROVIDERS:
            env[f"VGI_SCHOLAR_{name.upper()}_BASE_URL"] = server.base_url
        env["VGI_SCHOLAR_WORKER"] = worker

        print(f"mock provider server at {server.base_url}; running {haybarn} {pattern}")
        proc = subprocess.run(
            [haybarn, "--test-dir", test_dir, pattern],
            env=env,
        )
        return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
