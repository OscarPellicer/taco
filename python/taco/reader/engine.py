from __future__ import annotations

import threading
from typing import TYPE_CHECKING, cast

from ..errors import ContainerError

if TYPE_CHECKING:  # pragma: no cover - typing only
    import duckdb

_state = threading.local()


def open_reader() -> duckdb.DuckDBPyConnection:
    """Return one cached DuckDB connection per thread."""
    connection = cast("duckdb.DuckDBPyConnection | None", getattr(_state, "connection", None))
    if connection is not None:
        return connection
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ContainerError("reading a TACO dataset needs duckdb: pip install duckdb") from exc

    # Timestamps compare and print in UTC whatever the host timezone is.
    connection = duckdb.connect(config={"TimeZone": "UTC"})
    _state.connection = connection
    return connection


def close_reader() -> None:
    """Close the cached connection of the current thread."""
    connection = cast("duckdb.DuckDBPyConnection | None", getattr(_state, "connection", None))
    if connection is not None:
        try:
            connection.close()
        finally:
            del _state.connection


__all__ = ["close_reader", "open_reader"]
