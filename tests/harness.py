"""In-process VGI table-function invocation for the scholar test suite.

Runs a table function through the real bind -> init -> process lifecycle
(adapted from the vgi-embed harness), driving ``process()`` repeatedly until it
signals finish. State is the live :class:`_ScanState` object, so this exercises
the same cursor-advancement logic the framework uses on every tick.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
from vgi.arguments import Arguments
from vgi.function_storage import BoundStorage, FunctionStorage, FunctionStorageSqlite
from vgi.invocation import FunctionType
from vgi.protocol import BindRequest, InitRequest
from vgi.table_function import ProcessParams

_MAX_TICKS = 10_000  # guard against an accidental infinite loop in a test


def _test_storage() -> FunctionStorage:
    return FunctionStorageSqlite(":memory:")


class _MockOutputCollector:
    """Captures emitted batches for assertions."""

    def __init__(self, output_schema: pa.Schema) -> None:
        self.output_schema = output_schema
        self.batches: list[pa.RecordBatch] = []
        self._finished = False

    def emit(self, batch: pa.RecordBatch, *args: Any, **kwargs: Any) -> None:
        self.batches.append(batch)

    def finish(self) -> None:
        self._finished = True

    @property
    def finished(self) -> bool:
        return self._finished

    def emit_client_log_message(self, msg: Any) -> None:
        pass

    def client_log(self, *args: Any, **kwargs: Any) -> None:
        pass


def invoke_table_function(
    func_cls: type,
    positional: tuple[Any, ...] = (),
    named: dict[str, Any] | None = None,
) -> pa.Table:
    """Run a (source) table function through bind -> init -> process -> table.

    ``positional`` / ``named`` take plain Python values; they are wrapped as
    ``pa.Scalar`` here exactly as the C++ extension ships them to the worker.
    """
    args = Arguments(
        positional=tuple(pa.scalar(v) for v in positional),
        named={k: pa.scalar(v) for k, v in (named or {}).items()},
    )

    bind_req = BindRequest(
        function_name=func_cls.Meta.name,
        arguments=args,
        function_type=FunctionType.TABLE,
    )
    bind_resp = func_cls.bind(bind_req)

    init_req = InitRequest(bind_call=bind_req, output_schema=bind_resp.output_schema)
    init_resp = func_cls.global_init(init_req)

    storage = _test_storage()
    params = ProcessParams(
        args=func_cls._parse_arguments(func_cls.FunctionArguments, args),
        init_call=init_req,
        init_response=init_resp,
        output_schema=bind_resp.output_schema,
        settings={},
        secrets={},
        storage=BoundStorage(storage, init_resp.execution_id),
    )

    state = func_cls.initial_state(params)
    out = _MockOutputCollector(bind_resp.output_schema)

    ticks = 0
    while not out.finished:
        func_cls.process(params, state, out)
        ticks += 1
        if ticks > _MAX_TICKS:
            raise AssertionError(f"{func_cls.Meta.name} did not finish within {_MAX_TICKS} ticks")

    return pa.Table.from_batches(out.batches, schema=bind_resp.output_schema)
