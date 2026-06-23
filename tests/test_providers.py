"""Fixture parser unit tests: provider response -> unified Result mapping.

Each test feeds a captured, representative response (OpenAlex JSON, arXiv Atom
XML, Crossref JSON) through the provider's ``search`` by monkeypatching the
shared HTTP client, then asserts the unified-schema mapping: title/authors/doi/
year/published/venue/citations + the authors LIST, missing fields -> None, the
``extra`` JSON payload, and the next-page cursor.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from vgi_scholar import http_client
from vgi_scholar.providers.arxiv import ArxivProvider
from vgi_scholar.providers.crossref import CrossrefProvider
from vgi_scholar.providers.openalex import OpenAlexProvider

_FIXTURES = Path(__file__).parent / "fixtures"


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def json(self) -> Any:
        return json.loads(self.text)


def _patch_get(monkeypatch: pytest.MonkeyPatch, fixture: str) -> dict[str, Any]:
    """Patch http_client.get to return the named fixture; capture the call."""
    captured: dict[str, Any] = {}
    text = (_FIXTURES / fixture).read_text()

    def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return _FakeResponse(text)

    monkeypatch.setattr(http_client, "get", fake_get)
    return captured


# --------------------------------------------------------------------------
# OpenAlex
# --------------------------------------------------------------------------


class TestOpenAlex:
    def test_maps_unified_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_get(monkeypatch, "openalex.json")
        page = OpenAlexProvider("http://mock").search("rag", count=10, cursor=None, opts={})

        assert len(page.results) == 2
        first = page.results[0]
        assert first.source == "openalex"
        assert first.title.startswith("Retrieval-Augmented Generation")
        assert first.authors == ["Patrick Lewis", "Ethan Perez"]
        assert first.doi == "10.1234/rag"  # URL prefix stripped
        assert first.year == 2020
        assert first.published == datetime(2020, 5, 22, tzinfo=UTC)
        assert first.venue == "NeurIPS"
        assert first.citations_count == 4200
        assert first.url == "https://openalex.org/W1"
        # Abstract reconstructed from the inverted index, in position order.
        assert first.abstract == "We introduce retrieval-augmented generation."

    def test_missing_fields_become_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_get(monkeypatch, "openalex.json")
        page = OpenAlexProvider("http://mock").search("rag", count=10, cursor=None, opts={})
        second = page.results[1]
        assert second.doi is None
        assert second.authors is None  # empty authorships -> None
        assert second.abstract is None  # null inverted index
        assert second.venue is None
        assert second.year == 2020  # bare-year publication_date "2020"

    def test_extra_json_and_cursor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_get(monkeypatch, "openalex.json")
        page = OpenAlexProvider("http://mock").search("rag", count=10, cursor=None, opts={})
        extra = json.loads(page.results[0].extra_json())
        assert extra["openalex_id"] == "https://openalex.org/W1"
        assert extra["oa_status"] == "green"
        assert page.next_cursor  # non-null next cursor present

    def test_sends_mailto_and_cursor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _patch_get(monkeypatch, "openalex.json")
        OpenAlexProvider("http://mock").search("rag", count=7, cursor="ABC", opts={"mailto": "x@y.z"})
        assert captured["params"]["cursor"] == "ABC"
        assert captured["params"]["mailto"] == "x@y.z"
        assert captured["params"]["per_page"] == 7


# --------------------------------------------------------------------------
# arXiv
# --------------------------------------------------------------------------


class TestArxiv:
    def test_maps_unified_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_get(monkeypatch, "arxiv.xml")
        page = ArxivProvider("http://mock").search("rag", count=2, cursor=None, opts={})

        assert len(page.results) == 2
        first = page.results[0]
        assert first.source == "arxiv"
        # Whitespace in the multi-line <title> is collapsed.
        assert first.title == "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
        assert first.authors == ["Patrick Lewis", "Ethan Perez"]
        assert first.doi == "10.5555/arxivrag"
        assert first.published == datetime(2020, 5, 22, 17, 55, tzinfo=UTC)
        assert first.year == 2020
        assert first.venue == "NeurIPS 2020"
        assert first.citations_count is None  # arXiv exposes no citations
        assert first.url == "http://arxiv.org/abs/2005.11401v4"

    def test_missing_fields_become_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_get(monkeypatch, "arxiv.xml")
        page = ArxivProvider("http://mock").search("rag", count=2, cursor=None, opts={})
        second = page.results[1]
        assert second.doi is None  # no <arxiv:doi>
        assert second.venue == "arxiv"[0:0] or second.venue == "arXiv"  # default venue
        assert second.authors == ["Vladimir Karpukhin"]

    def test_extra_categories(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_get(monkeypatch, "arxiv.xml")
        page = ArxivProvider("http://mock").search("rag", count=2, cursor=None, opts={})
        extra = json.loads(page.results[0].extra_json())
        assert extra["categories"] == ["cs.CL", "cs.LG"]
        assert extra["primary_category"] == "cs.CL"
        assert extra["arxiv_id"] == "2005.11401v4"

    def test_offset_cursor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _patch_get(monkeypatch, "arxiv.xml")
        # A full page (2 results requested, 2 returned) -> next offset cursor.
        page = ArxivProvider("http://mock").search("rag", count=2, cursor="0", opts={})
        assert captured["params"]["start"] == 0
        assert page.next_cursor == "2"


# --------------------------------------------------------------------------
# Crossref
# --------------------------------------------------------------------------


class TestCrossref:
    def test_maps_unified_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_get(monkeypatch, "crossref.json")
        page = CrossrefProvider("http://mock").search("rag", count=10, cursor=None, opts={})

        first = page.results[0]
        assert first.source == "crossref"
        assert first.title == "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
        assert first.authors == ["Patrick Lewis", "Ethan Perez"]
        assert first.doi == "10.1234/rag"
        assert first.year == 2020
        assert first.published == datetime(2020, 5, 22, tzinfo=UTC)
        assert first.venue == "Advances in Neural Information Processing Systems"
        assert first.citations_count == 4200
        # JATS tags stripped from the abstract.
        assert first.abstract == "We introduce retrieval-augmented generation."

    def test_missing_fields_become_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_get(monkeypatch, "crossref.json")
        page = CrossrefProvider("http://mock").search("rag", count=10, cursor=None, opts={})
        second = page.results[1]
        assert second.venue is None  # empty container-title
        assert second.authors == ["Karpukhin"]  # family-only name
        assert second.abstract is None
        assert second.year == 2020  # bare-year date-parts [[2020]]

    def test_cursor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_get(monkeypatch, "crossref.json")
        page = CrossrefProvider("http://mock").search("rag", count=10, cursor=None, opts={})
        assert page.next_cursor == "AoJ3x+next+cursor+token"
