"""A tiny canned-response HTTP server for deterministic provider E2E tests.

Serves OpenAlex / arXiv / Crossref-shaped responses with **working pagination**
so tests can prove the cursor/offset scan-state round-trips across a batch
boundary: each provider returns one result per page and a non-null next cursor
until a fixed total is reached, then a final empty / cursor-less page.

Used two ways:

* in-process by ``test_mock_e2e.py`` (start, point providers at it, assert);
* as a subprocess by ``scripts/run_sql_e2e.py``, which exports the server URL
  into the ``VGI_SCHOLAR_*_BASE_URL`` env vars the worker reads, so the haybarn
  SQL suite drives the real worker against canned data — no live API in CI.

Pagination model (per provider, deterministic): ``_TOTAL`` results exist for any
query. Page N (0-based) returns result N and a cursor pointing at N+1, until
``_TOTAL`` is reached.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# How many synthetic results exist for any query, across all providers.
_TOTAL = 5


def _openalex_result(i: int) -> dict:
    return {
        "id": f"https://openalex.org/W{i}",
        "doi": f"https://doi.org/10.1234/work{i}" if i % 2 == 0 else None,
        "title": f"Mock OpenAlex Work {i}",
        "display_name": f"Mock OpenAlex Work {i}",
        "publication_year": 2020 + i,
        "publication_date": f"{2020 + i}-03-0{(i % 9) + 1}",
        "type": "article",
        "cited_by_count": 100 * i,
        "open_access": {"oa_status": "green"},
        "primary_location": {
            "landing_page_url": f"https://example.org/work/{i}",
            "source": {"display_name": f"Journal {i}"},
        },
        "authorships": [
            {"author": {"display_name": f"Ada Author{i}"}},
            {"author": {"display_name": f"Bob Builder{i}"}},
        ],
        "abstract_inverted_index": {"Mock": [0], "abstract": [1], f"{i}.": [2]},
    }


def _crossref_item(i: int) -> dict:
    return {
        "DOI": f"10.1234/work{i}",
        "URL": f"https://doi.org/10.1234/work{i}",
        "title": [f"Mock Crossref Work {i}"],
        "container-title": [f"Journal {i}"],
        "publisher": "Mock Press",
        "type": "journal-article",
        "is-referenced-by-count": 100 * i,
        "issued": {"date-parts": [[2020 + i, 3, (i % 9) + 1]]},
        "author": [
            {"given": "Ada", "family": f"Author{i}"},
            {"given": "Bob", "family": f"Builder{i}"},
        ],
    }


def _arxiv_entry(i: int) -> str:
    return f"""
  <entry>
    <id>http://arxiv.org/abs/20{i:02d}.0000{i}v1</id>
    <published>20{20 + i}-03-0{(i % 9) + 1}T00:00:00Z</published>
    <title>Mock arXiv Work {i}</title>
    <summary>Mock summary {i}.</summary>
    <author><name>Ada Author{i}</name></author>
    <author><name>Bob Builder{i}</name></author>
    <arxiv:primary_category term="cs.CL"/>
    <category term="cs.CL"/>
    <link href="http://arxiv.org/abs/20{i:02d}.0000{i}v1" rel="alternate" type="text/html"/>
  </entry>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # silence per-request logging
        pass

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path.endswith("/works") and "search" in qs:
            self._openalex(qs)
        elif parsed.path.endswith("/works"):
            self._crossref(qs)
        elif parsed.path.endswith("/query"):
            self._arxiv(qs)
        else:
            self._send(404, "text/plain", b"not found")

    # -- OpenAlex: cursor=* then opaque "p<N>" cursors -----------------------
    def _openalex(self, qs: dict) -> None:
        idx = _cursor_index(qs.get("cursor", ["*"])[0])
        if idx >= _TOTAL:
            body = {"meta": {"next_cursor": None}, "results": []}
        else:
            body = {
                "meta": {"next_cursor": f"p{idx + 1}"},
                "results": [_openalex_result(idx)],
            }
        self._send_json(body)

    # -- Crossref: cursor=* then "p<N>" --------------------------------------
    def _crossref(self, qs: dict) -> None:
        idx = _cursor_index(qs.get("cursor", ["*"])[0])
        if idx >= _TOTAL:
            body = {"message": {"next-cursor": None, "items": []}}
        else:
            body = {"message": {"next-cursor": f"p{idx + 1}", "items": [_crossref_item(idx)]}}
        self._send_json(body)

    # -- arXiv: start/max_results offset paging ------------------------------
    def _arxiv(self, qs: dict) -> None:
        start = int(qs.get("start", ["0"])[0])
        max_results = int(qs.get("max_results", ["10"])[0])
        entries = "".join(_arxiv_entry(i) for i in range(start, min(start + max_results, _TOTAL)))
        now = datetime.now(UTC).isoformat()
        feed = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:arxiv="http://arxiv.org/schemas/atom">'
            f"<updated>{now}</updated>{entries}</feed>"
        )
        self._send(200, "application/atom+xml", feed.encode("utf-8"))

    def _send_json(self, obj: dict) -> None:
        self._send(200, "application/json", json.dumps(obj).encode("utf-8"))

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _cursor_index(cursor: str) -> int:
    """Map an opaque cursor ('*' or 'p<N>') to a 0-based page index."""
    if cursor in ("", "*"):
        return 0
    if cursor.startswith("p"):
        try:
            return int(cursor[1:])
        except ValueError:
            return 0
    return 0


class MockServer:
    """A context-managed background HTTP server returning canned responses."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._httpd = ThreadingHTTPServer((host, port), _Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        host_str = host.decode() if isinstance(host, bytes) else host
        return f"http://{host_str}:{port}"

    @property
    def total(self) -> int:
        return _TOTAL

    def __enter__(self) -> MockServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def main() -> None:
    """Run the mock server out of band, printing ``URL:<base>`` then blocking.

    Used by ``ci/run-integration.sh`` (`python -m tests.mock_server`): it starts
    the server, advertises its bound URL on stdout for the harness to read, then
    blocks until killed so the URL stays valid for the whole SQL E2E run.
    """
    import time

    with MockServer() as server:
        print(f"URL:{server.base_url}", flush=True)
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
