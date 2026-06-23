"""The pluggable ``Provider`` protocol and shared parsing helpers.

A provider is a thin object that knows how to (a) build a request against one
scholarly API and (b) map that API's response into the unified
:class:`~vgi_scholar.schema_utils.Result` list, plus an opaque ``next_cursor``
used to fetch the following page.

The cursor is the **externalized scan state**: ``scholar_search`` carries it
across ``process()`` ticks (and, under HTTP transport, across requests) so a
single SQL scan can page through an arbitrary number of results. It is a plain
serializable string — the easy, non-stateful kind of pagination.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from ..schema_utils import Result


@dataclass(slots=True)
class Page:
    """One page of provider results plus the cursor for the next page.

    ``next_cursor`` is None when the provider has no more results (or cannot
    page further), which tells ``scholar_search`` to stop.
    """

    results: list[Result]
    next_cursor: str | None


class Provider(Protocol):
    """A scholarly-literature search backend.

    Implementations are cheap, stateless value objects; per-request state lives
    in the ``cursor`` argument, not on the provider. ``base_url`` is configurable
    so tests can point a provider at a mock HTTP server.
    """

    #: The provider's stable name (the value of the ``source`` column and the
    #: ``provider :=`` argument).
    name: str

    def search(self, query: str, count: int, cursor: str | None, opts: dict[str, Any]) -> Page:
        """Return one page of up to ``count`` results for ``query``.

        Args:
            query: The free-text search query.
            count: Page size (max results to return this call).
            cursor: Opaque pagination token from a previous page, or None to
                start at the beginning.
            opts: Provider-agnostic options (e.g. ``mailto``); providers ignore
                keys they do not understand.
        """
        ...


# --------------------------------------------------------------------------
# Parsing helpers shared across providers.
# --------------------------------------------------------------------------


def parse_year(value: Any) -> int | None:
    """Coerce a year-ish value into an int, or None."""
    if value is None:
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1 <= year <= 3000 else None


def parse_date(value: Any) -> datetime | None:
    """Parse an ISO-8601 date/datetime string into a tz-aware UTC datetime.

    Accepts ``YYYY``, ``YYYY-MM``, ``YYYY-MM-DD`` and full ISO timestamps.
    Naive inputs are assumed UTC. Returns None on anything unparseable.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # Normalize a trailing Z to +00:00 for fromisoformat.
    text = text.replace("Z", "+00:00")
    # Pad bare year / year-month so fromisoformat accepts them.
    if len(text) == 4 and text.isdigit():
        text = f"{text}-01-01"
    elif len(text) == 7 and text[4] == "-":
        text = f"{text}-01"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def date_parts_to_datetime(parts: list[Any] | None) -> datetime | None:
    """Build a UTC datetime from a Crossref-style ``[year, month, day]`` list."""
    if not parts:
        return None
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return datetime(year, month, day, tzinfo=UTC)
    except (TypeError, ValueError, IndexError):
        return None


def clean_doi(value: Any) -> str | None:
    """Normalize a DOI to its bare form (strip any URL / ``doi:`` prefix)."""
    if not value or not isinstance(value, str):
        return None
    doi = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
            break
    return doi or None
