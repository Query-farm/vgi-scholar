"""Optional live smoke test against the real OpenAlex API (free, no key).

GATED: runs only when ``VGI_SCHOLAR_LIVE=1`` is set, so it is never part of the
CI gate (which must not depend on a live external API). Run it manually:

    VGI_SCHOLAR_LIVE=1 uv run --no-sync pytest tests/test_live_smoke.py -q

It hits ``api.openalex.org`` once for a well-known query and asserts the unified
schema comes back populated. Be polite: set ``VGI_SCHOLAR_MAILTO`` first.
"""

from __future__ import annotations

import os

import pytest

from tests.harness import invoke_table_function
from vgi_scholar.schema_utils import UNIFIED_SCHEMA
from vgi_scholar.tables import ScholarSearchFunction

pytestmark = pytest.mark.skipif(
    os.environ.get("VGI_SCHOLAR_LIVE") != "1",
    reason="live smoke disabled; set VGI_SCHOLAR_LIVE=1 to run against api.openalex.org",
)


def test_openalex_live() -> None:
    table = invoke_table_function(
        ScholarSearchFunction,
        positional=("retrieval augmented generation",),
        named={"provider": "openalex", "count": 3},
    )
    assert table.schema.names == UNIFIED_SCHEMA.names
    assert table.num_rows == 3
    rows = table.to_pylist()
    assert all(r["source"] == "openalex" for r in rows)
    assert any(r["title"] for r in rows)
    assert any(isinstance(r["authors"], list) and r["authors"] for r in rows)
