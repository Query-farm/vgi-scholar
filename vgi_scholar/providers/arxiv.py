"""arXiv provider — https://export.arxiv.org/api (no API key, Atom XML).

arXiv's query API returns Atom XML and pages by ``start`` / ``max_results``
offset rather than a cursor. We encode the next offset as the cursor string so
``scholar_search`` can keep paging with the same machinery as the cursor-based
providers.

arXiv is a preprint repository: most works have no DOI and no citation count, so
those columns come back NULL — exactly what the unified-schema "missing -> NULL"
contract is for.
"""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from .. import http_client
from ..schema_utils import Result
from .base import Page, clean_doi, parse_date

DEFAULT_BASE_URL = "https://export.arxiv.org/api"

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


class ArxivProvider:
    """Search the arXiv ``/query`` endpoint (Atom XML, offset paging)."""

    name = "arxiv"

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        """Bind the provider to ``base_url`` (overridable for tests)."""
        self.base_url = base_url.rstrip("/")

    def search(self, query: str, count: int, cursor: str | None, opts: dict[str, Any]) -> Page:
        """Fetch one page of arXiv entries for ``query``."""
        start = _parse_offset(cursor)
        per_page = max(1, min(count, 200))
        params = {
            "search_query": f"all:{query}",
            "start": start,
            "max_results": per_page,
        }
        resp = http_client.get(f"{self.base_url}/query", params=params, accept="application/atom+xml")

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as exc:
            raise http_client.ProviderError(f"arXiv returned unparseable XML: {exc}") from exc

        entries = root.findall(f"{_ATOM}entry")
        results = [self._map(e) for e in entries]
        # If we got a full page, there may be more; advance the offset cursor.
        next_cursor = str(start + per_page) if len(results) == per_page else None
        return Page(results=results, next_cursor=next_cursor)

    @staticmethod
    def _map(entry: ET.Element) -> Result:
        title = _text(entry.find(f"{_ATOM}title"))
        summary = _text(entry.find(f"{_ATOM}summary"))
        authors = [
            name for author in entry.findall(f"{_ATOM}author") if (name := _text(author.find(f"{_ATOM}name")))
        ] or None

        published = parse_date(_text(entry.find(f"{_ATOM}published")))

        # The <id> is the arXiv abstract URL; prefer the explicit alternate link.
        url = _text(entry.find(f"{_ATOM}id"))
        for link in entry.findall(f"{_ATOM}link"):
            if link.get("rel") == "alternate" and link.get("href"):
                url = link.get("href")
                break

        venue = _text(entry.find(f"{_ARXIV}journal_ref")) or "arXiv"
        doi = clean_doi(_text(entry.find(f"{_ARXIV}doi")))

        extra: dict[str, Any] = {}
        categories = [c.get("term") for c in entry.findall(f"{_ATOM}category") if c.get("term")]
        if categories:
            extra["categories"] = categories
        primary = entry.find(f"{_ARXIV}primary_category")
        if primary is not None and primary.get("term"):
            extra["primary_category"] = primary.get("term")
        if url and "arxiv.org/abs/" in (url or ""):
            extra["arxiv_id"] = url.rsplit("/abs/", 1)[-1]

        return Result(
            source="arxiv",
            title=" ".join(title.split()) if title else None,
            authors=authors,
            abstract=" ".join(summary.split()) if summary else None,
            doi=doi,
            year=published.year if published else None,
            published=published,
            venue=venue,
            citations_count=None,  # arXiv exposes no citation count
            url=url,
            extra=extra,
        )


def _text(node: ET.Element | None) -> str | None:
    """Return stripped element text, or None."""
    if node is None or node.text is None:
        return None
    text = node.text.strip()
    return text or None


def _parse_offset(cursor: str | None) -> int:
    """Decode the offset cursor (defaults to 0)."""
    if not cursor:
        return 0
    try:
        return max(0, int(cursor))
    except ValueError:
        return 0
