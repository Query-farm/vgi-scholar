"""Provider registry: name -> :class:`~vgi_scholar.providers.base.Provider`.

``scholar_search(query, provider := 'openalex', ...)`` resolves the requested
provider name here. Adding a provider is: write the module, import it, register
it in ``_FACTORIES``. ``base_url`` is threaded through so tests can point any
provider at a mock HTTP server.
"""

from __future__ import annotations

from collections.abc import Callable

from .arxiv import ArxivProvider
from .base import Page, Provider
from .crossref import CrossrefProvider
from .openalex import OpenAlexProvider

#: The default provider when none is named.
DEFAULT_PROVIDER = "openalex"

#: Provider name -> factory taking an optional base_url override.
_FACTORIES: dict[str, Callable[[str | None], Provider]] = {
    "openalex": lambda base: OpenAlexProvider(base) if base else OpenAlexProvider(),
    "arxiv": lambda base: ArxivProvider(base) if base else ArxivProvider(),
    "crossref": lambda base: CrossrefProvider(base) if base else CrossrefProvider(),
}


def provider_names() -> list[str]:
    """All registered provider names, sorted."""
    return sorted(_FACTORIES)


def get_provider(name: str, base_url: str | None = None) -> Provider:
    """Resolve a provider by name, optionally overriding its base URL.

    Raises ValueError with the list of known providers on an unknown name, so
    SQL users get an actionable error instead of an empty result.
    """
    key = (name or DEFAULT_PROVIDER).strip().lower()
    factory = _FACTORIES.get(key)
    if factory is None:
        raise ValueError(f"unknown provider {name!r}; available providers: {', '.join(provider_names())}")
    return factory(base_url)


__all__ = [
    "DEFAULT_PROVIDER",
    "Page",
    "Provider",
    "get_provider",
    "provider_names",
]
