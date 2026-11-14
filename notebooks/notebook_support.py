"""Serve exact scholarly metadata recordings or configure direct live requests."""

import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import matplotlib.pyplot as plt
import seaborn as sns
from IPython.display import Markdown, display

ENVIRONMENT = tuple(f"VGI_SCHOLAR_{p}_BASE_URL" for p in ("OPENALEX", "CROSSREF", "ARXIV"))
QUERY = "attention is all you need transformer"
ROUTES = {
    "/openalex/works": ("openalex", {"search": [QUERY], "per_page": ["50"], "cursor": ["*"]}),
    "/crossref/works": (
        "crossref",
        {"query": [QUERY], "rows": ["50"], "cursor": ["*"], "sort": ["score"], "order": ["desc"]},
    ),
}


class ReplayHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        params.pop("mailto", None)
        self.server.requests.append(parsed.path)
        route = ROUTES.get(parsed.path)
        valid = route is not None and params == route[1]
        body = self.server.documents[route[0]] if valid else b'{"error":"unrecorded request"}'
        self.send_response(200 if valid else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def configure(mode, year):
    if mode not in ("replay", "live"):
        raise ValueError("DATA_MODE must be 'replay' or 'live'")
    if type(year) is not int or not 1900 <= year <= 2030:
        raise ValueError("MIN_YEAR must be an integer from 1900 through 2030 inclusive")
    previous = {key: os.environ.pop(key, None) for key in ENVIRONMENT}
    server = thread = None
    folder = Path(__file__).resolve().parent / "recordings"
    provenance = json.loads((folder / "provenance.json").read_text())
    if mode == "replay":
        documents = {name: (folder / f"{name}.json").read_bytes() for name in provenance}
        for name, body in documents.items():
            if hashlib.sha256(body).hexdigest() != provenance[name]["sha256"]:
                raise ValueError(f"Recording checksum mismatch: {name}")
        server = ThreadingHTTPServer(("127.0.0.1", 0), ReplayHandler)
        server.requests = []
        server.documents = documents
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        for provider in ("openalex", "crossref", "arxiv"):
            os.environ[f"VGI_SCHOLAR_{provider.upper()}_BASE_URL"] = base + "/" + provider
    return server, thread, previous, datetime.now(UTC).isoformat(), provenance


def audit(server):
    if server is not None:
        if sorted(server.requests) != sorted(ROUTES):
            raise AssertionError(f"Expected exactly two recorded requests: {server.requests}")
        return (
            "Replay audit: exactly one request to each recorded provider; query and page parameters matched."
        )
    return "Direct live requests; no replay server was created."


def cleanup(server, thread, previous):
    if server:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def prose(text: str) -> None:
    display(Markdown(text))


def theme() -> None:
    sns.set_theme(
        style="whitegrid",
        rc={
            "figure.dpi": 145,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": "#E8EDE9",
            "text.color": "#243B2F",
            "axes.labelcolor": "#405047",
            "text.parse_math": False,
            "legend.frameon": False,
        },
    )


def chart(fig, title: str, subtitle: str, source: str) -> None:
    fig.text(0.08, 0.98, title, ha="left", va="top", fontsize=17, fontweight="semibold")
    fig.text(0.08, 0.90, subtitle, ha="left", va="top", fontsize=10, color="#58685F")
    fig.tight_layout(rect=(0.02, 0.11, 1, 0.82))
    fig.text(0.08, 0.03, source, fontsize=8, color="#6C7D73")
    plt.show()
