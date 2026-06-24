"""``scholar_search`` and ``scholar_providers`` table functions.

``scholar_search(query, provider := 'openalex', count := 10, page_size := ...)``
is a **table function** (so it accepts DuckDB ``name := value`` arguments). It
streams up to ``count`` unified-schema rows for ``query`` from the chosen
provider, paging the provider as needed.

Pagination is the externalized scan state: the provider's opaque cursor lives in
:class:`_ScanState` (an ``ArrowSerializableDataclass``), which the framework
round-trips across ``process()`` ticks — and, under HTTP transport, across
independent requests. Each tick fetches one provider page, emits it, advances
the cursor, and stops when ``count`` rows are produced or the provider runs out.

Per-provider ``base_url`` overrides are read from environment variables
(``VGI_SCHOLAR_<PROVIDER>_BASE_URL``) so the test suite can point every provider
at a local mock HTTP server without touching SQL.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Annotated, ClassVar

import pyarrow as pa
from vgi.arguments import Arg
from vgi.invocation import BindResponse
from vgi.metadata import FunctionExample
from vgi.table_function import (
    BindParams,
    ProcessParams,
    TableCardinality,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc import ArrowSerializableDataclass
from vgi_rpc.rpc import OutputCollector

from . import http_client
from .providers import DEFAULT_PROVIDER, get_provider, provider_names
from .schema_utils import UNIFIED_SCHEMA, afield, results_to_batch

# Page size we request from a provider per tick when the caller does not pin one.
_DEFAULT_PAGE_SIZE = 25


def base_url_override(provider: str) -> str | None:
    """A per-provider base-URL override from the environment, or None.

    ``VGI_SCHOLAR_OPENALEX_BASE_URL`` overrides OpenAlex, etc. This is the seam
    the mock-server E2E uses to redirect every provider at a local test server.
    """
    value = os.environ.get(f"VGI_SCHOLAR_{provider.upper()}_BASE_URL")
    return value.strip() if value and value.strip() else None


@dataclass(slots=True, frozen=True)
class ScholarSearchArgs:
    """Arguments for ``scholar_search`` (a table function — named args allowed)."""

    query: Annotated[str, Arg(0, doc="Free-text search query.")]
    provider: Annotated[
        str,
        Arg("provider", default=DEFAULT_PROVIDER, doc="Provider name: 'openalex' (default), 'arxiv', or 'crossref'."),
    ]
    count: Annotated[int, Arg("count", default=10, doc="Maximum number of results to return.", ge=1, le=1000)]
    page_size: Annotated[
        int,
        Arg("page_size", default=0, doc="Results fetched per provider request (0 = an automatic size).", ge=0, le=200),
    ]


@dataclass(kw_only=True)
class _ScanState(ArrowSerializableDataclass):
    """Externalized pagination state carried across ``process()`` ticks.

    Attributes:
        cursor: The provider's opaque next-page token, or None to start / when
            exhausted. THIS is the scan state that round-trips across batches.
        emitted: How many rows we have emitted so far (to honor ``count``).
        started: False until the first tick runs (distinguishes "begin at the
            start" from "provider returned no further cursor").
        done: True once we should stop (count reached or provider exhausted).
    """

    cursor: str | None = None
    emitted: int = 0
    started: bool = False
    done: bool = False


@init_single_worker
@bind_fixed_schema
class ScholarSearchFunction(TableFunctionGenerator[ScholarSearchArgs, _ScanState]):
    """Search scholarly literature across pluggable providers, unified schema."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = UNIFIED_SCHEMA

    class Meta:
        """Function metadata."""

        name = "scholar_search"
        description = "Search academic literature (OpenAlex / arXiv / Crossref) into a unified schema"
        categories = ["search", "scholarly", "research", "rag"]
        examples = [
            FunctionExample(
                sql=(
                    "SELECT title, authors, year FROM "
                    "scholar.main.scholar_search('retrieval augmented generation', count := 5)"
                ),
                description="Top 5 OpenAlex results (the default provider) for a topic.",
            ),
            FunctionExample(
                sql=(
                    "SELECT title, doi FROM "
                    "scholar.main.scholar_search('graph neural networks', provider := 'crossref', count := 10)"
                ),
                description="Search Crossref instead of the default OpenAlex provider.",
            ),
            FunctionExample(
                sql=(
                    "SELECT title, published FROM "
                    "scholar.main.scholar_search('large language models', provider := 'arxiv', count := 20) "
                    "ORDER BY published DESC"
                ),
                description="Pull the 20 most recent arXiv preprints on a topic.",
            ),
        ]
        tags = {
            "vgi.title": "Scholarly Literature Search",
            "vgi.keywords": (
                "scholarly search, academic literature, papers, publications, openalex, arxiv, "
                "crossref, doi, citations, preprints, literature review, rag, retrieval"
            ),
            "vgi.source_url": ("https://github.com/Query-farm/vgi-scholar/blob/main/vgi_scholar/tables.py"),
            "vgi.doc_llm": (
                "## scholar_search\n\n"
                "Search scholarly / academic literature and stream up to `count` matching works as "
                "rows in a single **unified schema**, regardless of which provider answered. Use this "
                "whenever an agent needs to find papers by topic, resolve DOIs, gather citation counts, "
                "assemble a literature review, or build a corpus for retrieval-augmented generation (RAG).\n\n"
                "### Inputs\n"
                "- `query` (positional, VARCHAR) — free-text search string, e.g. `'retrieval augmented generation'`.\n"
                "- `provider :=` (VARCHAR, default `'openalex'`) — one of `'openalex'`, `'arxiv'`, `'crossref'`. "
                "Call `scholar_providers()` to enumerate the valid values.\n"
                "- `count :=` (INTEGER, default 10, 1–1000) — maximum rows to return; the function pages the "
                "provider until this budget is met or results are exhausted.\n"
                "- `page_size :=` (INTEGER, default 0, 0–200) — rows fetched per provider request; 0 picks an "
                "automatic page size.\n\n"
                "### Output\n"
                "One row per work in the unified schema (`title`, `authors`, `abstract`, `doi`, `year`, "
                "`published`, `venue`, `citations_count`, `url`, `source`, `extra`). `authors` is a "
                "`LIST<VARCHAR>`, `published` is a UTC `TIMESTAMPTZ`, and `extra` is provider-specific JSON.\n\n"
                "### Behavior & edge cases\n"
                "- No API key is required for any provider; set `VGI_SCHOLAR_MAILTO` to join the OpenAlex / "
                "Crossref polite pool.\n"
                "- An unknown `provider` is rejected at bind time with a clean DuckDB error.\n"
                "- Provider/network failures surface as a DuckDB error rather than crashing the worker.\n"
                "- Fields a provider does not supply (e.g. missing `doi` or `abstract`) come back as NULL.\n"
                "- Requires outbound network access to the provider's public API to return rows."
            ),
            "vgi.doc_md": (
                "# scholar_search\n\n"
                "Search scholarly literature across **OpenAlex** (default), **arXiv**, and **Crossref**, "
                "returning matches in one normalized schema so SQL never has to branch on the provider.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "-- Top 5 OpenAlex hits for a topic\n"
                "SELECT title, authors, year\n"
                "FROM scholar.main.scholar_search('retrieval augmented generation', count := 5);\n\n"
                "-- Most recent arXiv preprints\n"
                "SELECT title, published\n"
                "FROM scholar.main.scholar_search('large language models', provider := 'arxiv', count := 20)\n"
                "ORDER BY published DESC;\n"
                "```\n\n"
                "## Notes\n\n"
                "- `provider` accepts `openalex`, `arxiv`, or `crossref`; `scholar_providers()` lists them.\n"
                "- `count` (1–1000) caps the rows returned; the function pages the provider transparently.\n"
                "- No API key is needed. Set `VGI_SCHOLAR_MAILTO` for the polite pool.\n"
                "- Network access to the provider API is required; provider errors become DuckDB errors.\n\n"
                "See [`result_columns`](#) below for the returned columns."
            ),
            "vgi.result_columns_md": (
                "| column | type | description |\n"
                "|---|---|---|\n"
                "| `title` | VARCHAR | Work title. |\n"
                "| `authors` | LIST<VARCHAR> | Author display names, in listed order. |\n"
                "| `abstract` | VARCHAR | Abstract / summary text, when the provider exposes one. |\n"
                "| `doi` | VARCHAR | Digital Object Identifier (bare, e.g. `10.1234/abc`), when known. |\n"
                "| `year` | INTEGER | Publication year. |\n"
                "| `published` | TIMESTAMPTZ | Publication date as a UTC timestamp, when known. |\n"
                "| `venue` | VARCHAR | Journal / conference / repository name. |\n"
                "| `citations_count` | INTEGER | Number of citations the provider reports, when available. |\n"
                "| `url` | VARCHAR | A landing-page / record URL for the work. |\n"
                "| `source` | VARCHAR | The provider that produced this row (e.g. `openalex`). |\n"
                "| `extra` | JSON | Provider-specific fields not in the unified schema, JSON-encoded. |"
            ),
        }

    @classmethod
    def on_bind(cls, params: BindParams[ScholarSearchArgs]) -> BindResponse:
        """Validate the provider and pin the output schema at bind time."""
        # Validate the provider name at bind time so a typo is a clean DuckDB
        # error before any scan begins.
        get_provider(params.args.provider, base_url_override(params.args.provider))
        return BindResponse(output_schema=UNIFIED_SCHEMA)

    @classmethod
    def cardinality(cls, params: BindParams[ScholarSearchArgs]) -> TableCardinality:
        """Estimate the row count from the caller's ``count`` budget."""
        return TableCardinality(estimate=params.args.count, max=params.args.count)

    @classmethod
    def initial_state(cls, params: ProcessParams[ScholarSearchArgs]) -> _ScanState:
        """Return the fresh pagination state for a new scan."""
        return _ScanState()

    @classmethod
    def process(cls, params: ProcessParams[ScholarSearchArgs], state: _ScanState, out: OutputCollector) -> None:
        """Fetch and emit one provider page, advancing the pagination cursor."""
        a = params.args

        if state.done or state.emitted >= a.count:
            out.finish()
            return

        # On a continuation tick we have no cursor and we already started: the
        # provider had no further page, so we are done.
        if state.started and state.cursor is None:
            out.finish()
            return

        provider = get_provider(a.provider, base_url_override(a.provider))
        remaining = a.count - state.emitted
        per_page = a.page_size or min(_DEFAULT_PAGE_SIZE, remaining) or remaining

        try:
            page = provider.search(
                query=a.query,
                count=per_page,
                cursor=state.cursor,
                opts={"mailto": http_client.mailto()},
            )
        except (http_client.ProviderError, ValueError) as exc:
            # Never crash the worker: surface a clean DuckDB error.
            raise RuntimeError(f"scholar_search({a.provider!r}) failed: {exc}") from exc

        state.started = True

        # Trim to the caller's overall count budget.
        rows = page.results[:remaining]
        if rows:
            out.emit(results_to_batch(rows, params.output_schema))
            state.emitted += len(rows)

        state.cursor = page.next_cursor
        if page.next_cursor is None or state.emitted >= a.count:
            state.done = True

        if not rows and page.next_cursor is None:
            out.finish()


# ---------------------------------------------------------------------------
# Discovery: scholar_providers()
# ---------------------------------------------------------------------------


@dataclass(kw_only=True)
class _NoArgs:
    """A discovery table function that takes no arguments."""


_PROVIDERS_SCHEMA = pa.schema(
    [
        afield("provider", pa.string(), "Provider name to pass as provider := '...'.", nullable=False),
        afield(
            "requires_key",
            pa.bool_(),
            "Whether the provider needs an API key (all v1 providers are keyless).",
            nullable=False,
        ),
        afield("default", pa.bool_(), "Whether this is the default provider.", nullable=False),
    ]
)


@init_single_worker
@bind_fixed_schema
class ScholarProvidersFunction(TableFunctionGenerator[_NoArgs, None]):
    """List the available scholarly providers, one per row."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = _PROVIDERS_SCHEMA

    class Meta:
        """Function metadata."""

        name = "scholar_providers"
        description = "List the available scholarly-search providers"
        categories = ["search", "scholarly", "metadata"]
        examples = [
            FunctionExample(
                sql="SELECT * FROM scholar.main.scholar_providers()",
                description="Show every provider scholar_search can use.",
            ),
            FunctionExample(
                sql='SELECT provider FROM scholar.main.scholar_providers() WHERE "default"',
                description="Find the default provider used when scholar_search omits provider.",
            ),
        ]
        tags = {
            "vgi.title": "List Scholarly Providers",
            "vgi.keywords": (
                "providers, list providers, scholarly providers, openalex, arxiv, crossref, "
                "default provider, capability, discovery, requires key"
            ),
            "vgi.source_url": ("https://github.com/Query-farm/vgi-scholar/blob/main/vgi_scholar/tables.py"),
            "vgi.doc_llm": (
                "## scholar_providers\n\n"
                "Enumerate the scholarly-search providers that `scholar_search` can target, one per row. "
                "Use this to discover the valid values for `scholar_search`'s `provider :=` argument, to find "
                "the default provider, or to confirm a provider is keyless before running a search.\n\n"
                "### Inputs\n"
                "Takes no arguments.\n\n"
                "### Output\n"
                "One row per registered provider with `provider` (the name to pass as `provider := '...'`), "
                "`requires_key` (BOOLEAN — all current providers are keyless, so `false`), and `default` "
                "(BOOLEAN — true for the provider used when `scholar_search` omits `provider`).\n\n"
                "### Behavior & edge cases\n"
                "- Pure metadata: it makes **no** network calls and works without any external API, so it is "
                "always safe to run as a capability/discovery probe.\n"
                "- The set of providers is fixed at worker build time; the row order is the registration order."
            ),
            "vgi.doc_md": (
                "# scholar_providers\n\n"
                "List every scholarly-search provider available to `scholar_search`, one row each.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "-- Every provider scholar_search can use\n"
                "SELECT * FROM scholar.main.scholar_providers();\n\n"
                "-- The default provider\n"
                'SELECT provider FROM scholar.main.scholar_providers() WHERE "default";\n'
                "```\n\n"
                "## Notes\n\n"
                "- Returns metadata only — no network access is needed, so this is a reliable health/"
                "capability check for the worker.\n"
                "- All current providers are keyless (`requires_key = false`).\n"
                "- Exactly one row has `default = true`."
            ),
            "vgi.result_columns_md": (
                "| column | type | description |\n"
                "|---|---|---|\n"
                "| `provider` | VARCHAR | Provider name to pass as `provider := '...'`. |\n"
                "| `requires_key` | BOOLEAN | Whether the provider needs an API key (all v1 providers are keyless). |\n"
                "| `default` | BOOLEAN | Whether this is the default provider. |"
            ),
            "vgi.executable_examples": json.dumps(
                [
                    {
                        "description": "List every scholarly-search provider the worker exposes.",
                        "sql": "SELECT * FROM scholar.main.scholar_providers() ORDER BY provider",
                    },
                    {
                        "description": "Find the default provider used when scholar_search omits provider.",
                        "sql": 'SELECT provider FROM scholar.main.scholar_providers() WHERE "default"',
                    },
                    {
                        "description": "Confirm all providers are keyless (no API key required).",
                        "sql": (
                            "SELECT count(*) AS keyless FROM scholar.main.scholar_providers() WHERE NOT requires_key"
                        ),
                    },
                ]
            ),
        }

    @classmethod
    def cardinality(cls, params: BindParams[_NoArgs]) -> TableCardinality:
        """Estimate the row count as the number of registered providers."""
        n = len(provider_names())
        return TableCardinality(estimate=n, max=n)

    @classmethod
    def process(cls, params: ProcessParams[_NoArgs], state: None, out: OutputCollector) -> None:
        """Emit one row per registered provider, then finish."""
        names = provider_names()
        out.emit(
            pa.RecordBatch.from_pydict(
                {
                    "provider": names,
                    "requires_key": [False] * len(names),
                    "default": [n == DEFAULT_PROVIDER for n in names],
                },
                schema=params.output_schema,
            )
        )
        out.finish()


TABLE_FUNCTIONS: list[type] = [ScholarSearchFunction, ScholarProvidersFunction]
