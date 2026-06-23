"""Mock-server E2E: drive the scholar_search table function against canned HTTP.

Starts the local :class:`MockServer`, points every provider at it via the
``VGI_SCHOLAR_*_BASE_URL`` env vars, and runs ``scholar_search`` through the
real bind -> init -> process lifecycle. These assert the externally important
behavior end-to-end without any live network:

* the unified output schema (all 11 columns, correct types);
* ``authors`` comes back as a LIST<VARCHAR>;
* the cursor/offset scan-state ROUND-TRIPS across pages — a count larger than
  the mock's single-result page forces multiple ticks, and we get the full
  count back, in order, with no dupes;
* a provider error surfaces cleanly (raised, not a worker crash);
* an unknown provider is rejected at bind.
"""

from __future__ import annotations

from collections.abc import Iterator

import pyarrow as pa
import pytest

from tests.harness import invoke_table_function
from tests.mock_server import MockServer
from vgi_scholar.schema_utils import UNIFIED_SCHEMA
from vgi_scholar.tables import ScholarProvidersFunction, ScholarSearchFunction

PROVIDERS = ["openalex", "arxiv", "crossref"]


@pytest.fixture()
def mock_providers(monkeypatch: pytest.MonkeyPatch) -> Iterator[MockServer]:
    with MockServer() as server:
        for name in PROVIDERS:
            monkeypatch.setenv(f"VGI_SCHOLAR_{name.upper()}_BASE_URL", server.base_url)
        yield server


@pytest.mark.parametrize("provider", PROVIDERS)
def test_unified_schema_and_authors_list(provider: str, mock_providers: MockServer) -> None:
    table = invoke_table_function(
        ScholarSearchFunction, positional=("graphs",), named={"provider": provider, "count": 3}
    )
    # Exactly the unified columns, in order.
    assert table.schema.names == UNIFIED_SCHEMA.names
    # authors is a LIST<VARCHAR>.
    authors_type = table.schema.field("authors").type
    assert pa.types.is_list(authors_type)
    assert pa.types.is_string(authors_type.value_type)
    # published is a TIMESTAMPTZ.
    pub_type = table.schema.field("published").type
    assert pa.types.is_timestamp(pub_type) and pub_type.tz == "UTC"

    rows = table.to_pylist()
    assert len(rows) == 3
    assert rows[0]["source"] == provider
    assert isinstance(rows[0]["authors"], list)
    assert rows[0]["authors"] == ["Ada Author0", "Bob Builder0"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_scan_state_roundtrips_across_pages(provider: str, mock_providers: MockServer) -> None:
    """The mock returns ONE result per page; count=5 forces 5 paged ticks.

    If the cursor/offset scan-state did not round-trip across batches, we would
    re-fetch page 0 every tick (or stop after one row). Getting all 5 distinct
    results, in order, proves the state advances and is preserved.
    """
    total = mock_providers.total
    table = invoke_table_function(
        ScholarSearchFunction, positional=("graphs",), named={"provider": provider, "count": total, "page_size": 1}
    )
    rows = table.to_pylist()
    assert len(rows) == total
    titles = [r["title"] for r in rows]
    assert titles == sorted(set(titles), key=titles.index)  # no duplicates
    # Titles embed the page index, so order 0..total-1 confirms cursor advance.
    assert [t[-1] for t in titles] == [str(i) for i in range(total)]


def test_count_caps_below_available(mock_providers: MockServer) -> None:
    table = invoke_table_function(
        ScholarSearchFunction, positional=("graphs",), named={"provider": "openalex", "count": 2, "page_size": 1}
    )
    assert table.num_rows == 2


def test_provider_error_is_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    # Point openalex at a dead port so the request fails; assert it raises a
    # clean RuntimeError (a DuckDB error), not a worker-crashing exception.
    monkeypatch.setenv("VGI_SCHOLAR_OPENALEX_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setattr("vgi_scholar.http_client._sleep", lambda *_: None)  # no backoff wait
    with pytest.raises(RuntimeError, match="scholar_search"):
        invoke_table_function(ScholarSearchFunction, positional=("graphs",), named={"count": 1})


def test_unknown_provider_rejected_at_bind() -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        invoke_table_function(ScholarSearchFunction, positional=("q",), named={"provider": "nope"})


def test_scholar_providers_lists_all() -> None:
    table = invoke_table_function(ScholarProvidersFunction)
    assert table.schema.names == ["provider", "requires_key", "default"]
    rows = {r["provider"]: r for r in table.to_pylist()}
    assert set(rows) == set(PROVIDERS)
    assert rows["openalex"]["default"] is True
    assert all(r["requires_key"] is False for r in rows.values())
