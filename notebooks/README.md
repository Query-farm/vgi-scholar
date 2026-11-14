# Scholar notebooks

[Do two scholarly searches describe the same set of works?](01_compare_scholarly_search_coverage.ipynb)
audits metadata availability, joins exact normalized DOIs, and compares independent
citation observations under a publication-year window.

## Setup

Install uv and Git; this whole directory runs independently of the worker checkout.

```sh
cd notebooks
uv sync --locked
uv run python execute.py
uv run python -m ipykernel install --user --name vgi-scholar-notebooks --display-name 'Python (Scholar notebooks)'
uv run --with jupyterlab jupyter lab
```

Select that kernel interactively. The runner creates a temporary kernel spec and
executes with the notebook directory as cwd. Only success atomically replaces the
saved example. Published Haybarn **2.0.0rc11** has a separate locked environment.
Literal SQL launches public Git revision **66200a4d3e0b6b3360a67ef040b99d9b99fd3365**,
which includes explicit Crossref score sorting for cursor requests. uvx pins
Python 3.13, vgi-python 0.51.0, vgi-rpc 0.53.1, PyArrow 26.0.1 and httpx 0.28.1.
First launch needs network for Git/packages and the extension. No parent source or
worker environment is discovered. Update pins explicitly and rerun validation.

## Provenance and interpretation

The default replays **unchanged actual public responses**, captured on 14 November
2026 from OpenAlex and Crossref, 50 rows each for the fixed query
`attention is all you need transformer`. `recordings/provenance.json` contains
separate UTC capture times, full request URLs and SHA-256 checksums. Response
bodies are saved byte-for-byte; they are separate observations, not an atomic
snapshot. Retrieval dates are distinct from the returned publication dates.

The loopback-only server checks checksums, paths and query/page/sort parameters;
only the contact `mailto` parameter is ignored for matching. It serves through the
worker's supported `VGI_SCHOLAR_*_BASE_URL` hooks. An audit requires exactly one
request per recorded provider. Live mode clears all three inherited base-URL
hooks and creates no replay server; errors are surfaced without fallback.
Cleanup restores prior settings. arXiv is discovered but not queried here.

For optional live runs, set `VGI_SCHOLAR_MAILTO` to your own contact address in
the launching environment for the providers' polite pool; it is never printed by
the notebook. Without it the worker uses its documented placeholder contact.
OpenAlex metadata is CC0; Crossref metadata and linked content follow their
respective reuse terms. No provider endorsement is implied. Citation counts are
provider observations, not quality scores. A bounded search intersection is not
a systematic review, completeness estimate, or measure of index recall.

## Experiments

```sh
uv run python execute.py --parameters '{"MIN_YEAR":2024}' --output-dir artifacts/year-2024
uv run python execute.py --parameters '{"DATA_MODE":"live"}' --output-dir artifacts/live
```

MIN_YEAR is an integer 1900–2030 inclusive; unknown years are diagnosed separately
and excluded. DATA_MODE is replay or live. The filter applies after the same
50-row request to each provider. Repeated DOI rows are excluded from one-to-one
matching and explicitly counted. Null citation counts remain unavailable, not zero.
Overrides require a separate destination. Copies include recordings, branding,
helpers, runner, documentation and environment files. Restore MIN_YEAR=2022.

## Validation

Validated with published Haybarn 2.0.0rc11: 15 code cells, 6 visible SQL cells,
2 charts, 12 SQL invariants and an exact two-request replay audit. Default passed
in 27.5 seconds including first pinned worker launch. A notebooks-only detached
copy passed the year-2024 experiment in 22.0 seconds, live mode in 7.8 seconds,
and empty-window year-2030 boundary in 2.9 seconds. All eight charts were reviewed.
Three rejected-run guards preserve the successful default.

The focused year change 2022→2024 reduces selected rows 80→65 and shared DOI keys
11→8; unchanged response bytes fix the input. The 2030 window returns zero
selected rows and an explicit unavailable paired chart. The direct live run
returned the same aggregate counts as the default at 2026-11-14 10:06:15 UTC.

Source checks passed: 22 pytest tests (one opt-in live smoke skipped), 57 stdio /
59 HTTP / 57 Unix SQL assertions, Ruff lint/format including notebooks, mypy on
12 source files, isolated pydoclint and frozen dependency synchronization/lock
check. Full live metadata validation passed **100/100 L2 with zero findings**.
The same metadata gate against the source test fixtures reports one VGI902 warning
because a composed DOI example has no fixture intersection; structural validation
is clear. This fixture limitation is distinct from the passing live metadata gate.
Worker source and root dependency lockfiles are unchanged.
