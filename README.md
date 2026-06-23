<p align="center">
  <img src="https://raw.githubusercontent.com/Query-farm/vgi/main/docs/vgi-logo.png" alt="Vector Gateway Interface (VGI)" width="320">
</p>

<p align="center"><em>A <a href="https://query.farm">Query.Farm</a> VGI worker for DuckDB.</em></p>

# Scholarly Search across OpenAlex, arXiv & Crossref in DuckDB

> **vgi-scholar** · a [Query.Farm](https://query.farm) VGI worker

A [VGI](https://github.com/query-farm/vgi-python) worker that searches
**scholarly literature** from DuckDB/SQL across multiple **free, ToS-clean**
providers behind one pluggable surface. Every provider is normalized into a
single unified schema, so a query never has to know which API produced a row.

```sql
INSTALL vgi FROM community; LOAD vgi;
ATTACH 'scholar' (TYPE vgi, LOCATION 'uv run scholar_worker.py');

-- top-N results from OpenAlex (the default provider)
SELECT title, authors, year, doi, citations_count
FROM scholar.scholar_search('retrieval augmented generation', count := 10);

-- search Crossref or arXiv instead
SELECT title, doi FROM scholar.scholar_search('graph neural networks', provider := 'crossref', count := 5);
SELECT title, url FROM scholar.scholar_search('diffusion models',    provider := 'arxiv',    count := 5);

-- which providers are available?
SELECT * FROM scholar.scholar_providers();
```

`scholar_search` is a **table function**, so it accepts DuckDB's
`name := value` arguments. It pages each provider as needed to satisfy `count`,
carrying the provider's cursor/offset as externalized scan state.

## Why this worker

This completes the AI/RAG retrieval stack with a **clean academic vertical**: no
scraping, no licensing landmines, no API keys. It pairs naturally with
`vgi-embed` (vectors) and a reranker — search papers, embed the abstracts, feed
an LLM. Unlike a generic web-search wrapper, scholarly metadata (authors, DOI,
venue, citation counts, dates) deserves its own rich schema, which is what this
worker provides.

## Providers (v1)

All three v1 providers are **free and require no API key**.

| Provider | API | Pagination | Strengths | Typical NULLs |
| --- | --- | --- | --- | --- |
| **openalex** *(default)* | `api.openalex.org` | cursor (`cursor=*`) | richest metadata; abstracts (inverted index); citation counts | — |
| **arxiv** | `export.arxiv.org/api` | `start`/`max_results` offset | preprints, full abstracts, categories | `doi`, `citations_count` |
| **crossref** | `api.crossref.org` | cursor deep-paging | DOIs, citation counts, publishers | `abstract` (rarely present) |

`provider := '...'` selects one; omit it for OpenAlex. Unknown names raise a
clear error listing the available providers.

### Polite-pool norms (please configure)

OpenAlex and Crossref run a faster, more reliable **"polite pool"** for clients
that identify themselves with a contact e-mail. This worker always sends a
descriptive `User-Agent`; set your contact address so it also sends `mailto`:

```sh
export VGI_SCHOLAR_MAILTO="you@example.org"
```

Every request has a **per-call timeout** and a **bounded retry with backoff** on
`429`/`5xx`. A provider failure becomes a clean DuckDB error — it never crashes
the worker.

## Unified result schema

`scholar_search` always returns exactly these columns; a provider that lacks a
field leaves it `NULL`.

| column | type | notes |
| --- | --- | --- |
| `title` | VARCHAR | |
| `authors` | LIST&lt;VARCHAR&gt; | author display names, in listed order |
| `abstract` | VARCHAR | when the provider exposes one |
| `doi` | VARCHAR | bare DOI (e.g. `10.1234/abc`), URL/`doi:` prefix stripped |
| `year` | INTEGER | publication year |
| `published` | TIMESTAMPTZ | publication date (UTC) when known |
| `venue` | VARCHAR | journal / conference / repository |
| `citations_count` | INTEGER | provider's citation count when available |
| `url` | VARCHAR | landing-page / record URL |
| `source` | VARCHAR | the provider that produced the row |
| `extra` | VARCHAR (JSON) | provider-specific fields, JSON-encoded |

## Function catalog

### `scholar_search(query, provider := 'openalex', count := 10, page_size := 0)` → unified schema  *(table function)*

Search `query` and stream up to `count` unified-schema rows from `provider`.

- `query` — free-text query (positional).
- `provider` — `'openalex'` (default), `'arxiv'`, or `'crossref'`.
- `count` — maximum rows to return (1–1000).
- `page_size` — rows fetched per provider request (0 = an automatic size). The
  worker pages the provider until `count` is satisfied or results run out;
  pagination is the externalized scan state.

### `scholar_providers()` → `(provider, requires_key, default)`  *(table function)*

List the available providers. All v1 providers have `requires_key = false`.

## Pagination / scan state

Each provider's opaque cursor (OpenAlex/Crossref) or numeric offset (arXiv) is
carried in a small serializable scan-state object that the VGI framework
round-trips across `process()` ticks — and, under HTTP transport, across
independent requests. This is the *easy*, serializable kind of pagination (not
the hard stateful kind like Kafka offsets), and the SQL E2E suite asserts it
round-trips across a page boundary.

## Planned (deferred) lookups

These fit the same provider surface and are planned for a future version:

- `scholar_by_doi(doi)` — fetch one work by DOI (OpenAlex/Crossref support
  direct DOI lookup).
- `scholar_citations(doi)` — works citing a DOI (OpenAlex's `cites:` filter).

## Local development

```sh
uv venv --python 3.13
uv pip install -e ../vgi-python httpx pyarrow pytest ruff mypy
uv pip install -e . --no-deps

make test            # pytest (fixture parsers + mock-server E2E) + SQL E2E (haybarn, mock server)
make test-unit       # pytest only — NO live network
make test-sql        # DuckDB sqllogictest E2E, driven against the local mock server
make lint            # ruff
make typecheck       # mypy
```

### Testing approach (no live APIs in the CI gate)

- **Fixture parser unit tests** (`tests/test_providers.py`) — a captured,
  representative response per provider (`tests/fixtures/`) is mapped to the
  unified schema; covers missing-field → NULL, the authors LIST, the `extra`
  JSON, and cursor extraction.
- **Mock-server E2E** (`tests/test_mock_e2e.py`) — a local HTTP server
  (`tests/mock_server.py`) serves canned, *paged* responses; every provider's
  `base_url` is pointed at it. Asserts the unified schema, `authors` as a LIST,
  the **scan-state round-trip across pages**, a clean provider-error path, and
  unknown-provider rejection.
- **haybarn SQL E2E** (`test/sql/scholar_search.test`) — the real worker
  subprocess under DuckDB via
  [`haybarn-unittest`](https://pypi.org/project/haybarn-unittest/), with its
  providers redirected at the mock server (`scripts/run_sql_e2e.py`).
- **Optional live smoke** (`tests/test_live_smoke.py`, gated by
  `VGI_SCHOLAR_LIVE=1`) — one real OpenAlex query (free, no key). Not in the CI
  gate.

> Developing against a local `vgi-python` checkout? `[tool.uv.sources]` in
> `pyproject.toml` already points there; or `uv pip install -e ../vgi-python`.

## Layout

```
scholar_worker.py        entry point; assembles the `scholar` catalog, serves over stdio
serve.py                 HTTP entrypoint
vgi_scholar/
  schema_utils.py        unified Arrow schema + Result + result->RecordBatch
  http_client.py         polite, bounded-retry HTTP client (timeout, 429/5xx backoff, UA/mailto)
  providers/
    base.py              Provider protocol + shared parse helpers (dates, DOIs)
    openalex.py          OpenAlex (default, cursor paging, inverted-index abstracts)
    arxiv.py             arXiv (Atom XML, offset paging)
    crossref.py          Crossref (cursor deep-paging, JATS abstract stripping)
    __init__.py          provider registry / get_provider
  tables.py              scholar_search + scholar_providers table functions
tests/
  fixtures/              one captured response per provider (JSON / XML)
  mock_server.py         canned, paged HTTP server (in-process + subprocess)
  test_providers.py      fixture parser unit tests
  test_mock_e2e.py       mock-server E2E (schema, authors LIST, scan-state round-trip, errors)
  test_live_smoke.py     optional gated live OpenAlex smoke
test/sql/
  scholar_search.test    DuckDB sqllogictest E2E against the mock server
scripts/run_sql_e2e.py   starts the mock server, exports its URL, runs the haybarn glob
```

## Licensing

- **Worker code: MIT** (see [LICENSE](LICENSE)).
- Python dependencies are permissive (`httpx`, `pyarrow`, `vgi-python`).
- **Provider APIs** are accessed over plain HTTP (no bundled SDKs). Each is free
  and ToS-clean for this metadata-search use:
  - **OpenAlex** — CC0 data; asks clients to identify via `mailto` (polite pool).
  - **arXiv** — public API; respect its rate limits and reuse policy.
  - **Crossref** — open metadata; asks clients to send `mailto` for the polite
    pool.
  Set `VGI_SCHOLAR_MAILTO` and stay within each API's documented rate limits.
  You are responsible for complying with each provider's terms.

---

## Authorship & License

Written by [Query.Farm](https://query.farm).

Copyright 2026 Query Farm LLC - https://query.farm

