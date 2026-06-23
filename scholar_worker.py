# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python>=0.8.3",
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

_SCHOLAR_CATALOG = Catalog(
    name="scholar",
    default_schema="main",
    schemas=[
        Schema(
            name="main",
            comment="Search scholarly literature (OpenAlex / arXiv / Crossref) into a unified schema",
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
