"""Shared Arrow-schema helpers and the unified scholarly-result schema.

Every provider maps its native response into a :class:`Result`, and
``scholar_search`` emits that as the single unified Arrow schema defined here.
Keeping the schema in one place guarantees every provider returns *exactly* the
same columns (missing fields become SQL NULL), so a query never has to know
which provider produced a row.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa


def afield(
    name: str,
    type: pa.DataType,
    comment: str,
    *,
    nullable: bool = True,
) -> pa.Field:
    """Build a ``pa.Field`` carrying a column comment in its metadata.

    The ``comment`` metadata key is the framework's transport for column
    comments -- DuckDB surfaces it via ``duckdb_columns()`` and ``DESCRIBE``.
    """
    return pa.field(
        name,
        type,
        nullable=nullable,
        metadata={b"comment": comment.encode("utf-8")},
    )


# TIMESTAMPTZ in DuckDB is microsecond precision with a UTC tz marker; LIST and
# JSON returns REQUIRE an explicit arrow_type (the SDK rejects bare AnyArrow for
# parameterized types), so we pin them here once.
_TIMESTAMPTZ = pa.timestamp("us", tz="UTC")
_AUTHORS = pa.list_(pa.string())

# JSON-typed VARCHAR: a plain Arrow string field tagged so DuckDB treats it as
# JSON. The tag is the field metadata key the VGI framework maps to DuckDB's
# JSON logical type.
_JSON_FIELD_META = {
    b"comment": b"Provider-specific fields not in the unified schema, JSON-encoded.",
    b"logical_type": b"JSON",
}


#: The single unified output schema produced by ``scholar_search`` for every
#: provider. Order matters: it is the column order callers see.
UNIFIED_SCHEMA: pa.Schema = pa.schema(
    [
        afield("title", pa.string(), "Work title."),
        afield("authors", _AUTHORS, "Author display names, in listed order (LIST<VARCHAR>)."),
        afield("abstract", pa.string(), "Abstract / summary text, when the provider exposes one."),
        afield("doi", pa.string(), "Digital Object Identifier (bare, e.g. '10.1234/abc'), when known."),
        afield("year", pa.int32(), "Publication year."),
        afield("published", _TIMESTAMPTZ, "Publication date as a UTC timestamp, when known (TIMESTAMPTZ)."),
        afield("venue", pa.string(), "Journal / conference / repository name."),
        afield("citations_count", pa.int32(), "Number of citations the provider reports, when available."),
        afield("url", pa.string(), "A landing-page / record URL for the work."),
        afield("source", pa.string(), "The provider that produced this row (e.g. 'openalex').", nullable=False),
        pa.field("extra", pa.string(), nullable=True, metadata=_JSON_FIELD_META),
    ]
)


@dataclass(slots=True)
class Result:
    """A single scholarly work, normalized across providers.

    Every field except ``source`` is optional; a provider sets what it knows and
    leaves the rest as ``None`` (rendered as SQL NULL). ``extra`` is a free-form
    dict of provider-specific fields that gets JSON-encoded into the ``extra``
    column.
    """

    source: str
    title: str | None = None
    authors: list[str] | None = None
    abstract: str | None = None
    doi: str | None = None
    year: int | None = None
    published: Any = None  # datetime | None — kept Any so providers can pass aware datetimes
    venue: str | None = None
    citations_count: int | None = None
    url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def extra_json(self) -> str | None:
        """Serialize ``extra`` to a JSON string, or None when empty."""
        if not self.extra:
            return None
        return json.dumps(self.extra, ensure_ascii=False, default=str, sort_keys=True)


def results_to_batch(results: list[Result], schema: pa.Schema = UNIFIED_SCHEMA) -> pa.RecordBatch:
    """Build a single RecordBatch in the unified schema from a list of results.

    ``schema`` is the (possibly projected) output schema DuckDB asked for; we
    build all unified columns then select the ones the schema names, so
    projection pushdown is honored without per-provider code.
    """
    columns: dict[str, list[Any]] = {
        "title": [r.title for r in results],
        "authors": [r.authors for r in results],
        "abstract": [r.abstract for r in results],
        "doi": [r.doi for r in results],
        "year": [r.year for r in results],
        "published": [r.published for r in results],
        "venue": [r.venue for r in results],
        "citations_count": [r.citations_count for r in results],
        "url": [r.url for r in results],
        "source": [r.source for r in results],
        "extra": [r.extra_json() for r in results],
    }
    arrays = [pa.array(columns[name], type=schema.field(name).type) for name in schema.names]
    return pa.RecordBatch.from_arrays(arrays, schema=schema)
