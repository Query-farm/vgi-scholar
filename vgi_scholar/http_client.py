"""A small, polite HTTP client shared by every provider.

Network discipline (mirrors vgi-translate / vgi-embed worker discipline):

* **Per-call timeout** — every request has a bounded timeout so a hung provider
  can never wedge a DuckDB scan.
* **Bounded retry with backoff on 429 / 5xx** — transient rate-limit and server
  errors are retried a few times with exponential backoff; everything else
  fails fast.
* **Polite pool identification** — a descriptive ``User-Agent`` and, where the
  API asks for it (OpenAlex, Crossref), a ``mailto``. Free academic APIs grant
  faster, more reliable service to identified clients; being a good citizen is
  both polite and practical.
* **Never crash the worker** — providers translate failures into a
  :class:`ProviderError`, which the table function turns into a clean DuckDB
  error rather than a worker crash.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

#: Default per-request timeout (seconds). Overridable per call.
DEFAULT_TIMEOUT = 20.0
#: How many times to retry a 429/5xx before giving up (so up to N+1 attempts).
DEFAULT_RETRIES = 3
#: Base backoff (seconds); doubles each retry.
_BACKOFF_BASE = 0.5

#: Contact e-mail advertised to polite-pool APIs. Operators SHOULD set this.
_MAILTO_ENV = "VGI_SCHOLAR_MAILTO"
_DEFAULT_MAILTO = "vgi-scholar@example.com"

_VERSION = "0.1.0"


class ProviderError(RuntimeError):
    """A provider could not satisfy a request (network, HTTP, or parse error).

    Carries a human-readable message safe to surface as a DuckDB error.
    """


def mailto() -> str:
    """The contact e-mail to advertise to polite-pool APIs (env-overridable)."""
    return os.environ.get(_MAILTO_ENV, _DEFAULT_MAILTO).strip() or _DEFAULT_MAILTO


def user_agent() -> str:
    """A descriptive User-Agent including a contact address (polite-pool norm)."""
    return f"vgi-scholar/{_VERSION} (https://query.farm; mailto:{mailto()})"


def _sleep(seconds: float) -> None:
    """Indirection so tests can monkeypatch the backoff sleep to a no-op."""
    time.sleep(seconds)


def get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    accept: str | None = None,
) -> httpx.Response:
    """GET ``url`` with the polite headers, a timeout, and bounded retry.

    Retries on 429 and 5xx with exponential backoff (honoring ``Retry-After``
    when present). Raises :class:`ProviderError` on exhausted retries, transport
    errors, or a non-retryable error status.
    """
    base_headers = {"User-Agent": user_agent()}
    if accept:
        base_headers["Accept"] = accept
    if headers:
        base_headers.update(headers)

    last_error: str = "unknown error"
    for attempt in range(retries + 1):
        try:
            resp = httpx.get(url, params=params, headers=base_headers, timeout=timeout, follow_redirects=True)
        except httpx.HTTPError as exc:  # transport-level: DNS, connect, read timeout, etc.
            last_error = f"request to {url} failed: {exc}"
            if attempt < retries:
                _sleep(_BACKOFF_BASE * (2**attempt))
                continue
            raise ProviderError(last_error) from exc

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = f"{url} returned HTTP {resp.status_code}"
            if attempt < retries:
                _sleep(_retry_after(resp) or _BACKOFF_BASE * (2**attempt))
                continue
            raise ProviderError(last_error)

        if resp.status_code >= 400:
            # Client error (400/401/403/404, …): not retryable.
            raise ProviderError(f"{url} returned HTTP {resp.status_code}: {resp.text[:200]}")

        return resp

    raise ProviderError(last_error)


def _retry_after(resp: httpx.Response) -> float | None:
    """Parse a numeric ``Retry-After`` header into seconds, if present."""
    value = resp.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
