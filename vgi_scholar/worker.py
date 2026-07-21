# Copyright 2026 Query Farm LLC - https://query.farm

"""VGI worker exposing scholarly-literature search to DuckDB/SQL.

Assembles the table functions in :mod:`vgi_scholar.tables` into a single
``scholar`` catalog and runs the worker over stdio (a DuckDB subprocess) or
HTTP (``serve.py`` / the ``vgi-serve`` console script).

Search runs against FREE, ToS-clean scholarly APIs behind one pluggable
provider surface: OpenAlex (default), arXiv, and Crossref. No API key is
required for any v1 provider. Results are normalized into a single unified
schema so a query never has to know which provider produced a row.

This module is the wheel-importable home of the worker. The repo-root
``scholar_worker.py`` is a thin PEP-723 shim that re-exports
:class:`ScholarWorker` and :func:`main` from here, so ``uv run
scholar_worker.py`` (the Makefile / ci/run-integration.sh / tests) keeps
working unchanged.

Usage:
    vgi-scholar-worker                   # serve over stdio (DuckDB subprocess)
    uv run scholar_worker.py             # serve over stdio (DuckDB subprocess)
    python serve.py --port 8000          # serve over HTTP

    INSTALL vgi FROM community; LOAD vgi;
    ATTACH 'scholar' (TYPE vgi, LOCATION 'uv run scholar_worker.py');

    SELECT title, authors, year, doi
    FROM scholar.scholar_search('retrieval augmented generation', count := 5);

    SELECT * FROM scholar.scholar_providers();

Be a good API citizen: set VGI_SCHOLAR_MAILTO to your contact e-mail so the
worker joins OpenAlex's and Crossref's faster "polite pool".
"""

from __future__ import annotations

import json

from vgi import Worker
from vgi.catalog import Catalog, Schema, Table

from vgi_scholar.tables import TABLE_FUNCTIONS, ScholarProvidersFunction

_CATALOG_DESCRIPTION_LLM = (
    "Search scholarly / academic literature from SQL across free, ToS-clean providers "
    "(OpenAlex by default, plus arXiv and Crossref) behind one pluggable surface, with "
    "results normalized into a single unified schema (title, authors, abstract, doi, year, "
    "published, venue, citations_count, url, source, extra). Use it to find papers by topic, "
    "pull DOIs and citation counts, build literature reviews, or feed retrieval-augmented "
    "generation (RAG) pipelines. No API key is required for any provider. "
    "`scholar_search(query, provider := ..., count := ...)` returns matching works; "
    "`scholar_providers()` lists the available providers."
)

_CATALOG_DESCRIPTION_MD = (
    "# Scholarly Literature Search in SQL\n\n"
    "**Search academic papers, preprints, and citations directly from DuckDB/SQL** "
    "across [OpenAlex](https://docs.openalex.org), [arXiv](https://arxiv.org), and "
    "[Crossref](https://www.crossref.org) — three free, ToS-clean scholarly APIs unified "
    "behind one pluggable query surface, with no API key required.\n\n"
    "The `scholar` catalog turns the world's open scholarly-metadata graph into ordinary "
    "SQL tables. It is built for researchers, data engineers, librarians, and anyone wiring "
    "up retrieval-augmented generation (RAG) pipelines who would rather write a query than "
    "glue together three different REST clients. Every search returns the **same unified "
    "result schema** — `title`, `authors`, `abstract`, `doi`, `year`, `published`, `venue`, "
    "`citations_count`, `url`, `source`, and a JSON `extra` column — so a query never has to "
    "know or care which provider produced a given row. Switch providers with a single named "
    "argument and the rest of your SQL stays identical.\n\n"
    "Under the hood the worker talks plain HTTP to each provider's public API: the "
    "[OpenAlex API](https://docs.openalex.org) (the open catalog of ~250M scholarly works, "
    "used by default), the [arXiv API](https://info.arxiv.org/help/api/index.html) for "
    "physics, math, and CS preprints, and the [Crossref REST API]"
    "(https://www.crossref.org/documentation/retrieve-metadata/rest-api/) for DOI-registered "
    "publications. Results are fetched page by page and streamed back to DuckDB as Arrow, so "
    "large result sets never have to be buffered in full. Pagination cursors round-trip "
    "through the worker, retries back off on rate limits, and a provider error surfaces as a "
    "clean SQL error rather than crashing the attach.\n\n"
    "## Table functions\n\n"
    "- `scholar_search(query, provider := 'openalex', count := 10, page_size := 0)` — full-text "
    "search scholarly works and stream up to `count` rows in the unified schema. Pass "
    "`provider := 'arxiv'` or `provider := 'crossref'` to target a different source.\n"
    "- `scholar_providers()` — list every provider `scholar_search` can target (also queryable "
    "as the table `scholar.main.scholar_providers`), with its keyless and default flags.\n\n"
    "## Getting started\n\n"
    "Install and load the signed `vgi` community extension, `ATTACH` this worker at a "
    "`LOCATION` such as `uv run scholar_worker.py`, and then call the two table functions "
    "directly. Ready-to-run, copy-paste queries live in this schema's example queries and in "
    "each function's own examples, so they are executed and coverage-checked rather than "
    "duplicated inline here.\n\n"
    "Typical uses: find papers by topic, resolve and enrich DOIs, gather citation counts, "
    "assemble a literature-review corpus, or feed a RAG index — all without leaving SQL. "
    "**No API key is required** for any provider; set `VGI_SCHOLAR_MAILTO` to your contact "
    "e-mail to join OpenAlex's and Crossref's faster \"polite pool\".\n\n"
    "Powered by [OpenAlex](https://docs.openalex.org) "
    "([source](https://github.com/ourresearch/openalex-guts)), "
    "[arXiv](https://arxiv.org) "
    "([API docs](https://info.arxiv.org/help/api/index.html)), and "
    "[Crossref](https://www.crossref.org) "
    "([REST API docs](https://github.com/CrossRef/rest-api-doc))."
)

_SCHEMA_DESCRIPTION_LLM = (
    "## scholar.main\n\n"
    "Scholarly-literature search functions returning a single **unified result schema**. "
    "`scholar_search(query, provider := ..., count := ...)` searches OpenAlex / arXiv / Crossref "
    "for works matching a free-text query and streams up to `count` rows (title, authors, abstract, "
    "doi, year, published, venue, citations_count, url, source, extra). `scholar_providers()` lists "
    "the providers available to `scholar_search`, one per row. Use this schema to find papers by "
    "topic, resolve DOIs, gather citation counts, or build a corpus for retrieval-augmented "
    "generation. No API key is required; set `VGI_SCHOLAR_MAILTO` for the polite pool."
)

_SCHEMA_DESCRIPTION_MD = (
    "# scholar.main\n\n"
    "Scholarly-literature search over **OpenAlex**, **arXiv**, and **Crossref**, normalized into a "
    "single unified schema.\n\n"
    "## Functions\n\n"
    "- `scholar_search(query, provider := 'openalex', count := 10)` — search works and stream "
    "unified-schema rows.\n"
    "- `scholar_providers()` — list the providers `scholar_search` can target.\n\n"
    "## Notes\n\n"
    "No API key is required for any provider. Set `VGI_SCHOLAR_MAILTO` to join the OpenAlex / "
    "Crossref polite pool. `scholar_search` requires outbound network access; `scholar_providers` "
    "is pure metadata and always runs offline."
)

_CATALOG_TAGS = {
    "vgi.title": "Scholarly Literature Search",
    "vgi.keywords": json.dumps(
        [
            "scholarly search",
            "academic literature",
            "papers",
            "publications",
            "openalex",
            "arxiv",
            "crossref",
            "doi",
            "citations",
            "preprints",
            "literature review",
            "rag",
            "retrieval",
            "research",
        ]
    ),
    "vgi.doc_llm": _CATALOG_DESCRIPTION_LLM,
    "vgi.doc_md": _CATALOG_DESCRIPTION_MD,
    "vgi.author": "Query.Farm",
    "vgi.copyright": "Copyright 2026 Query Farm LLC - https://query.farm",
    "vgi.license": "MIT",
    "vgi.support_contact": "https://github.com/Query-farm/vgi-scholar/issues",
    "vgi.support_policy_url": "https://github.com/Query-farm/vgi-scholar/blob/main/README.md",
    # Fixed analyst-task suite for `vgi-lint simulate` (VGI152/VGI520/VGI920). The
    # provider-discovery tasks grade against `scholar_providers()`, which is pure,
    # offline metadata (no network), so their references are deterministic. The
    # `scholar_search` task instead grades a stable yes/no THRESHOLD predicate
    # (does a common query return at least N works?) that returns a single BOOLEAN
    # — robust against live-provider result variation, which an exact-compare
    # reference on `scholar_search` rows could never be.
    "vgi.agent_test_tasks": json.dumps(
        [
            {
                "name": "list_providers",
                "prompt": (
                    "Which scholarly-search providers can this worker query? Return a single column "
                    "listing only each provider's name, one provider per row."
                ),
                "reference_sql": "SELECT provider FROM scholar.main.scholar_providers()",
                "unordered": True,
                "ignore_column_names": True,
            },
            {
                "name": "default_provider",
                "prompt": (
                    "When a scholarly search does not specify a provider, which provider is "
                    "used by default? Return just that provider's name."
                ),
                "reference_sql": 'SELECT provider FROM scholar.main.scholar_providers() WHERE "default"',
                "ignore_column_names": True,
            },
            {
                "name": "keyless_provider_count",
                "prompt": ("How many of the available scholarly-search providers can be used without an API key?"),
                "reference_sql": (
                    "SELECT count(*) AS keyless FROM scholar.main.scholar_providers() WHERE NOT requires_key"
                ),
                "ignore_column_names": True,
            },
            {
                "name": "search_finds_works",
                "prompt": (
                    'Search the scholarly literature for the topic "machine learning" and determine '
                    "whether at least three matching works are found. Answer with a single true/false value."
                ),
                "reference_sql": (
                    "SELECT count(*) >= 3 AS found FROM scholar.main.scholar_search('machine learning', count := 5)"
                ),
                "ignore_column_names": True,
            },
        ]
    ),
}

# VGI515/VGI514: a JSON list of described {description, sql} examples (not a bare
# SQL string, and no trivial `SELECT *`) so each schema example carries prose and
# demonstrates a real projection/filter.
_SCHEMA_EXAMPLE_QUERIES = json.dumps(
    [
        {
            "description": "List each provider with its keyless and default flags, alphabetically.",
            "sql": ('SELECT provider, requires_key, "default" FROM scholar.main.scholar_providers ORDER BY provider'),
        },
        {
            "description": "Find the default provider used when scholar_search omits provider.",
            "sql": 'SELECT provider FROM scholar.main.scholar_providers WHERE "default"',
        },
        {
            "description": "Fetch the top 5 OpenAlex (default provider) results for a topic.",
            "sql": (
                "SELECT title, authors, year FROM "
                "scholar.main.scholar_search('retrieval augmented generation', count := 5)"
            ),
        },
        {
            "description": "Search Crossref instead of the default provider and pull DOIs.",
            "sql": (
                "SELECT title, doi FROM "
                "scholar.main.scholar_search('graph neural networks', provider := 'crossref', count := 10)"
            ),
        },
    ]
)

_SCHEMA_TAGS = {
    "vgi.title": "Scholar — main",
    "vgi.keywords": json.dumps(
        [
            "scholar_search",
            "scholar_providers",
            "scholarly search",
            "academic literature",
            "openalex",
            "arxiv",
            "crossref",
            "doi",
            "citations",
            "literature review",
            "rag",
        ]
    ),
    # VGI123 classifying tags use BARE keys (NOT vgi.-namespaced).
    "domain": "research",
    "category": "search",
    "topic": "scholarly-literature",
    "vgi.doc_llm": _SCHEMA_DESCRIPTION_LLM,
    "vgi.doc_md": _SCHEMA_DESCRIPTION_MD,
    "vgi.example_queries": _SCHEMA_EXAMPLE_QUERIES,
    # Navigation registry (VGI408-413): an ordered list of categories that the
    # schema's objects are grouped under. Each object carries a matching
    # `vgi.category` naming one of these.
    "vgi.categories": json.dumps(
        [
            {
                "name": "Search",
                "description": (
                    "Full-text scholarly search that streams matching works (title, authors, "
                    "DOI, year, citations, …) into one unified result schema."
                ),
            },
            {
                "name": "Providers",
                "description": (
                    "Discover the scholarly-search providers the worker can target, which is "
                    "the default, and whether each is keyless."
                ),
            },
        ]
    ),
}

_PROVIDERS_TABLE_TAGS = {
    "vgi.title": "Scholarly Providers",
    "vgi.keywords": json.dumps(
        [
            "providers",
            "list providers",
            "scholarly providers",
            "openalex",
            "arxiv",
            "crossref",
            "default provider",
            "capability",
            "discovery",
            "requires key",
        ]
    ),
    "domain": "research",
    "category": "search",
    "topic": "scholarly-literature",
    "vgi.category": "Providers",
    "vgi.doc_llm": (
        "## scholar_providers (table)\n\n"
        "The fixed set of scholarly-search providers that `scholar_search` can target, one row per "
        "provider. This is the table form of the `scholar_providers()` function: because it takes no "
        "arguments and always returns the same rows, you can read it as a plain table — "
        "`scholar.main.scholar_providers`, no parentheses — rather than calling it as a function. "
        "Use it to discover the valid values for "
        "`scholar_search`'s `provider :=` argument, to find the default provider, or to confirm a "
        "provider is keyless before running a search.\n\n"
        "Columns: `provider` (the name to pass as `provider := '...'`; unique per row and the table's "
        "primary key), `requires_key` (true if the provider needs an API key — all current providers "
        "are keyless, so false), and `default` (true for the single provider used when `scholar_search` "
        "omits `provider`). Reading this table makes no network calls."
    ),
    "vgi.doc_md": (
        "# scholar_providers (table)\n\n"
        "Every scholarly-search provider available to `scholar_search`, one row each. This is the "
        "table form of the parameterless `scholar_providers()` function.\n\n"
        "Read it with no parentheses, e.g. `scholar.main.scholar_providers`, to enumerate the "
        'valid `provider :=` values, filter on the `"default"` flag to see which provider is '
        "used when a search omits `provider`, or count the `requires_key` column to confirm a "
        "provider is keyless. Runnable examples are attached as this table's example queries.\n\n"
        "## Columns\n\n"
        "- `provider` (`VARCHAR`, primary key) — name to pass as `provider := '...'`.\n"
        "- `requires_key` (`BOOLEAN`) — whether the provider needs an API key (all v1 providers are keyless).\n"
        "- `default` (`BOOLEAN`) — whether this is the default provider; exactly one row is true.\n\n"
        "## Notes\n\n"
        "Reading this table needs no network access, so it is a reliable capability/health probe."
    ),
    "vgi.example_queries": json.dumps(
        [
            {
                "description": "List each provider with its keyless and default flags, alphabetically.",
                "sql": (
                    'SELECT provider, requires_key, "default" FROM scholar.main.scholar_providers ORDER BY provider'
                ),
            },
            {
                "description": "Find the default provider used when scholar_search omits provider.",
                "sql": 'SELECT provider FROM scholar.main.scholar_providers WHERE "default"',
            },
            {
                "description": "Confirm all providers are keyless (no API key required).",
                "sql": "SELECT count(*) AS keyless FROM scholar.main.scholar_providers WHERE NOT requires_key",
            },
        ]
    ),
}

_PROVIDERS_TABLE = Table(
    name="scholar_providers",
    function=ScholarProvidersFunction,
    comment=(
        "One row per scholarly-search provider scholar_search can target (provider name, keyless flag, default flag)"
    ),
    not_null=("provider", "requires_key", "default"),
    primary_key=(("provider",),),
    tags=_PROVIDERS_TABLE_TAGS,
)

_SCHOLAR_CATALOG = Catalog(
    name="scholar",
    default_schema="main",
    comment="Scholarly-literature search across OpenAlex, arXiv, and Crossref, unified for SQL and RAG",
    tags=_CATALOG_TAGS,
    source_url="https://github.com/Query-farm/vgi-scholar",
    schemas=[
        Schema(
            name="main",
            comment=(
                "Scholarly-search table functions: scholar_search (query works) and scholar_providers (list providers)"
            ),
            tags=_SCHEMA_TAGS,
            functions=list(TABLE_FUNCTIONS),
            # scholar_providers takes no arguments and always returns the same
            # provider rows, so also expose it as a regular table — callers can
            # then run `SELECT * FROM scholar.main.scholar_providers` (no
            # parentheses) in addition to the table-function call form.
            tables=[_PROVIDERS_TABLE],
        ),
    ],
)


class ScholarWorker(Worker):
    """Worker process hosting the ``scholar`` catalog."""

    catalog = _SCHOLAR_CATALOG


def main() -> None:
    """Run the scholar worker process (stdio or, via flags, HTTP)."""
    ScholarWorker.main()


if __name__ == "__main__":
    main()
