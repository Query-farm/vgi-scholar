"""Crossref provider — https://api.crossref.org (no API key, deep paging).

Crossref indexes DOI-registered works (journals, conferences, books). It pages
with a ``cursor`` ("deep paging"): start at ``cursor=*`` and follow the
``next-cursor`` from each response. We join the polite pool with a ``mailto``.

Crossref rarely carries abstracts (and when it does they are JATS XML), so the
abstract column is usually NULL here; DOIs and citation counts are its strength.
"""

from __future__ import annotations

import re
from typing import Any

from .. import http_client
from ..schema_utils import Result
from .base import Page, clean_doi, date_parts_to_datetime, parse_year

DEFAULT_BASE_URL = "https://api.crossref.org"

_JATS_TAG_RE = re.compile(r"<[^>]+>")


class CrossrefProvider:
    """Search Crossref ``/works`` with cursor deep-paging."""

    name = "crossref"

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def search(self, query: str, count: int, cursor: str | None, opts: dict[str, Any]) -> Page:
        params: dict[str, Any] = {
            "query": query,
            "rows": max(1, min(count, 100)),
            "cursor": cursor or "*",
        }
        mailto = opts.get("mailto") or http_client.mailto()
        if mailto:
            params["mailto"] = mailto

        resp = http_client.get(f"{self.base_url}/works", params=params, accept="application/json")
        payload = resp.json()
        message = payload.get("message", {})

        results = [self._map(item) for item in message.get("items", [])]
        next_cursor = message.get("next-cursor")
        if not results:
            next_cursor = None
        return Page(results=results, next_cursor=next_cursor)

    @staticmethod
    def _map(item: dict[str, Any]) -> Result:
        titles = item.get("title") or []
        title = titles[0] if titles else None

        author_names = [
            " ".join(part for part in (a.get("given"), a.get("family")) if part).strip()
            for a in item.get("author", [])
        ]
        authors = [a for a in author_names if a] or None

        containers = item.get("container-title") or []
        venue = containers[0] if containers else None

        issued = (item.get("issued") or {}).get("date-parts") or []
        published = date_parts_to_datetime(issued[0] if issued else None)
        year = published.year if published else parse_year(item.get("published-print", {}).get("year"))

        extra: dict[str, Any] = {}
        if item.get("type"):
            extra["type"] = item["type"]
        if item.get("publisher"):
            extra["publisher"] = item["publisher"]

        return Result(
            source="crossref",
            title=title,
            authors=authors,
            abstract=_strip_jats(item.get("abstract")),
            doi=clean_doi(item.get("DOI")),
            year=year,
            published=published,
            venue=venue,
            citations_count=item.get("is-referenced-by-count"),
            url=item.get("URL"),
            extra=extra,
        )


def _strip_jats(value: Any) -> str | None:
    """Strip JATS/XML tags from a Crossref abstract, or None."""
    if not value or not isinstance(value, str):
        return None
    text = _JATS_TAG_RE.sub("", value).strip()
    return " ".join(text.split()) or None
