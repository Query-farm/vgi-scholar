"""OpenAlex provider — https://api.openalex.org (no API key, the default).

OpenAlex is the richest free, ToS-clean scholarly source: full metadata, no key,
and true cursor pagination (``cursor=*`` then follow ``meta.next_cursor``). It is
the default provider.

Abstracts arrive as an *inverted index* (``abstract_inverted_index``: token ->
positions); we reconstruct the plain text. We send a ``mailto`` to join the
faster "polite pool".
"""

from __future__ import annotations

from typing import Any

from .. import http_client
from ..schema_utils import Result
from .base import Page, clean_doi, parse_date, parse_year

DEFAULT_BASE_URL = "https://api.openalex.org"


class OpenAlexProvider:
    """Search OpenAlex ``/works``."""

    name = "openalex"

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def search(self, query: str, count: int, cursor: str | None, opts: dict[str, Any]) -> Page:
        params: dict[str, Any] = {
            "search": query,
            "per_page": max(1, min(count, 200)),
            "cursor": cursor or "*",
        }
        mailto = opts.get("mailto") or http_client.mailto()
        if mailto:
            params["mailto"] = mailto

        resp = http_client.get(f"{self.base_url}/works", params=params, accept="application/json")
        payload = resp.json()

        results = [self._map(work) for work in payload.get("results", [])]
        # OpenAlex echoes the *next* cursor; it returns a non-null cursor even on
        # the last page, so stop when a page comes back short/empty.
        next_cursor = payload.get("meta", {}).get("next_cursor")
        if not results:
            next_cursor = None
        return Page(results=results, next_cursor=next_cursor)

    @staticmethod
    def _map(work: dict[str, Any]) -> Result:
        authors = [
            a["author"]["display_name"]
            for a in work.get("authorships", [])
            if a.get("author", {}).get("display_name")
        ] or None

        primary = work.get("primary_location") or {}
        venue = (primary.get("source") or {}).get("display_name")

        extra: dict[str, Any] = {}
        if work.get("id"):
            extra["openalex_id"] = work["id"]
        if work.get("type"):
            extra["type"] = work["type"]
        if work.get("open_access", {}).get("oa_status"):
            extra["oa_status"] = work["open_access"]["oa_status"]

        return Result(
            source="openalex",
            title=work.get("title") or work.get("display_name"),
            authors=authors,
            abstract=_reconstruct_abstract(work.get("abstract_inverted_index")),
            doi=clean_doi(work.get("doi")),
            year=parse_year(work.get("publication_year")),
            published=parse_date(work.get("publication_date")),
            venue=venue,
            citations_count=work.get("cited_by_count"),
            url=primary.get("landing_page_url") or work.get("id"),
            extra=extra,
        )


def _reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """Rebuild abstract text from OpenAlex's inverted index, or None."""
    if not inverted:
        return None
    positions: list[tuple[int, str]] = []
    for token, where in inverted.items():
        for pos in where:
            positions.append((pos, token))
    if not positions:
        return None
    positions.sort(key=lambda p: p[0])
    return " ".join(token for _, token in positions)
