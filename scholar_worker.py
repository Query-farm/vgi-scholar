# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http]>=0.8.4",
#     "httpx>=0.27",
# ]
# ///
"""VGI worker exposing scholarly-literature search to DuckDB/SQL.

Assembles the table functions in ``vgi_scholar`` into a single ``scholar``
catalog and runs the worker over stdio (a DuckDB subprocess) or HTTP (serve.py).

Search runs against FREE, ToS-clean scholarly APIs behind one pluggable
provider surface: OpenAlex (default), arXiv, and Crossref. No API key is
required for any v1 provider. Results are normalized into a single unified
schema so a query never has to know which provider produced a row.

Usage:
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

from vgi import Worker
from vgi.catalog import Catalog, Schema

from vgi_scholar.tables import TABLE_FUNCTIONS

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
    "# scholar\n\n"
    "Search scholarly literature from DuckDB/SQL across free, ToS-clean providers "
    "(**OpenAlex** (default), **arXiv**, **Crossref**) behind one pluggable surface, "
    "normalized into a single unified result schema.\n\n"
    "Table functions:\n\n"
    "- `scholar_search(query, provider := 'openalex', count := 10, page_size := 0)` "
    "— search works and stream up to `count` unified-schema rows.\n"
    "- `scholar_providers()` — list the available providers.\n\n"
    "No API key is required. Set `VGI_SCHOLAR_MAILTO` to join OpenAlex/Crossref's "
    "polite pool."
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
    "vgi.keywords": (
        "scholarly search, academic literature, papers, publications, openalex, arxiv, crossref, "
        "doi, citations, preprints, literature review, rag, retrieval, research"
    ),
    "vgi.doc_llm": _CATALOG_DESCRIPTION_LLM,
    "vgi.doc_md": _CATALOG_DESCRIPTION_MD,
    "vgi.author": "Query.Farm",
    "vgi.copyright": "Copyright 2026 Query Farm LLC - https://query.farm",
    "vgi.license": "MIT",
    "vgi.support_contact": "https://github.com/Query-farm/vgi-scholar/issues",
    "vgi.support_policy_url": "https://github.com/Query-farm/vgi-scholar/blob/main/README.md",
}

_SCHEMA_SOURCE_URL = "https://github.com/Query-farm/vgi-scholar/blob/main/scholar_worker.py"

_SCHEMA_EXAMPLE_QUERIES = (
    "SELECT * FROM scholar.main.scholar_providers();\n"
    'SELECT provider FROM scholar.main.scholar_providers() WHERE "default";\n'
    "SELECT title, authors, year FROM "
    "scholar.main.scholar_search('retrieval augmented generation', count := 5);\n"
    "SELECT title, doi FROM "
    "scholar.main.scholar_search('graph neural networks', provider := 'crossref', count := 10);"
)

_SCHEMA_TAGS = {
    "vgi.title": "Scholar — main",
    "vgi.keywords": (
        "scholar_search, scholar_providers, scholarly search, academic literature, openalex, "
        "arxiv, crossref, doi, citations, literature review, rag"
    ),
    # VGI123 classifying tags use BARE keys (NOT vgi.-namespaced).
    "domain": "research",
    "category": "search",
    "topic": "scholarly-literature",
    "vgi.source_url": _SCHEMA_SOURCE_URL,
    "vgi.doc_llm": _SCHEMA_DESCRIPTION_LLM,
    "vgi.doc_md": _SCHEMA_DESCRIPTION_MD,
    "vgi.example_queries": _SCHEMA_EXAMPLE_QUERIES,
}

_SCHOLAR_CATALOG = Catalog(
    name="scholar",
    default_schema="main",
    comment="Scholarly-literature search across OpenAlex, arXiv, and Crossref, unified for SQL and RAG",
    tags=_CATALOG_TAGS,
    source_url="https://github.com/Query-farm/vgi-scholar",
    schemas=[
        Schema(
            name="main",
            comment="Scholarly-search table functions: scholar_search (query works) and scholar_providers (list providers)",
            tags=_SCHEMA_TAGS,
            functions=list(TABLE_FUNCTIONS),
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
