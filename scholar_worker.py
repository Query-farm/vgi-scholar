# /// script
# requires-python = ">=3.13"
# dependencies = [
#     # 0.46.x speaks VGI protocol 2.x, which the signed vgi community extension
#     # requires; keep at >=0.46.1 (older releases speak protocol 1.x and ATTACH
#     # fails with a protocol_version mismatch).
#     "vgi-python[http]>=0.46.1",
#     "httpx>=0.27",
# ]
# ///
"""VGI worker entrypoint for scholarly-literature search (PEP-723 shim).

The worker itself — the ``scholar`` catalog, :class:`ScholarWorker`, and
:func:`main` — lives in the wheel-importable :mod:`vgi_scholar.worker`. This
repo-root script is a thin shim that re-exports them so ``uv run
scholar_worker.py`` (the Makefile, ci/run-integration.sh, and the tests) keeps
working unchanged, while the packaged distribution installs a ``vgi-scholar-worker``
console script pointing at the same :func:`main`.

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

from vgi_scholar.worker import ScholarWorker, main

__all__ = ["ScholarWorker", "main"]


if __name__ == "__main__":
    main()
