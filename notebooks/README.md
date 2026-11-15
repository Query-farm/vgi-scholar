# Scholarly Literature Search notebooks

[Audit the samples before comparing scholarly search coverage](01_compare_scholarly_search_coverage.ipynb)
asks whether two bounded searches support a DOI comparison. It discovers keyless
providers, retrieves each sample once, inspects full publication-year context, and
partitions year-eligible rows by DOI identity. Both public SQL names are used
meaningfully; `scholar_providers` has a table alias, counted once.
[Coverage evidence](coverage.json) records complete release/current runtime catalogs
and the released notebook's execution receipts and editorial review.

## Portable setup

The example uses **Scholar v0.4.0**, Haybarn 2.0.0rc11 and shared notebook tooling
v0.3.45. Shared setup supplies proper catalog branding, SVG/GitHub presentation,
UTC and an empty temporary SQL-secret directory with persistence disabled. The short
`uvx --python 3.13 --from ...@v0.4.0` command isolates worker libraries from the kernel;
no source checkout, compilation or transitive overrides are needed. First use needs
Git/network access. Colab installs only the shared **base** package and retrieves
four checksum-verified companions; local `uv.lock` includes the `[runner]` extra.
Hosted Colab was not manually executed; fresh Python 3.12 preloaded-kernel
compatibility is tested separately.

## Real recordings and release semantics

Default `DATA_MODE="replay"` serves unchanged public JSON bodies to the real worker
through its supported local base-URL hooks. No SQL computation is substituted in
Python. [Provenance](recordings/provenance.json) gives exact URLs/parameters, UTC
capture times, HTTP status and body SHA256 digests. OpenAlex was captured on
14 November 2026 and Crossref on 15 November UTC: independent observations, not an
atomic snapshot. Each contains 50 rows. Provider terms apply:
[OpenAlex](https://docs.openalex.org/) and
[Crossref](https://www.crossref.org/documentation/retrieve-metadata/rest-api/).

Released Crossref cursor requests omit `sort=score&order=desc`. Its new recording
matches that request and contains older works with no DOI overlap with this
OpenAlex sample. It replaces the earlier current-source sorted recording, preserved
in Git history. Replaying sorted results for an unsorted release request would
misrepresent the result. Immutable release/current Crossref source evidence is in
`coverage/`; current public source adds explicit sorting. Both actual runtime
catalogs have the same two names, but no current analytical execution is claimed.

The story checks **comparability before interpreting overlap**. Zero matches do not
mean the full provider indexes have no works in common. Titles, identifiers, years
and missingness remain visible. The joined table retains paired citations when
identity supports them; approximate title matching does not invent pairings.
Provider availability and access policies can change independently of the release.

## Run and change one parameter

From this directory:

```sh
uv sync --locked
uv run --locked vgi-notebooks 01_compare_scholarly_search_coverage.ipynb --timeout 600
uv run --locked vgi-notebooks 01_compare_scholarly_search_coverage.ipynb --param MIN_YEAR=2024 --output-dir artifacts/year-2024 --timeout 600
uv run --locked vgi-notebooks 01_compare_scholarly_search_coverage.ipynb --param MIN_YEAR=2030 --output-dir artifacts/year-2030 --timeout 600
```

2022 → 2024 changes only the local inclusive year cutoff: OpenAlex eligibility
falls from 39 to 31, while Crossref remains zero. Full source-year distributions and
recordings stay unchanged. At 2030 both selected bars are zero, with both providers
retained. Override runs require a separate output directory, preserving saved
defaults; experiment copies have native SVG rather than unpublished image links.

An explicit bounded live refresh, without fallback:

```sh
uv run --locked vgi-notebooks 01_compare_scholarly_search_coverage.ipynb --param DATA_MODE='"live"' --output-dir artifacts/live --timeout 600
```

This makes one 50-row request per provider, subject to bounded retries. It uses the
release's request semantics and may return different metadata or fail. Optional
`VGI_SCHOLAR_MAILTO` comes from the environment; never save private contact details
or credentials. Default replay uses no provider account or outbound API requests.

Validation covers 14 SQL invariants, exact two-request replay audits, default,
2024 experiment, 2030 boundary, fresh preloaded notebook-only setup, runner guards,
reviewed figures and public GitHub SVG rendering. Unchanged green worker source CI
is reused rather than repeating builds or source/container workflows.
