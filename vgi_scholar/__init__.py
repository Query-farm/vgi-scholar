"""vgi-scholar: search scholarly literature from SQL across free providers.

The public surface is the ``scholar`` catalog assembled in
``scholar_worker.py``; this package holds its pieces:

* :mod:`vgi_scholar.providers` — the pluggable provider protocol + OpenAlex,
  arXiv, and Crossref implementations.
* :mod:`vgi_scholar.tables` — the ``scholar_search`` / ``scholar_providers``
  table functions.
* :mod:`vgi_scholar.schema_utils` — the unified result schema + ``Result``.
* :mod:`vgi_scholar.http_client` — the polite, bounded-retry HTTP client.
"""

from __future__ import annotations

__version__ = "0.1.0"
