from __future__ import annotations

import json
from collections.abc import Sequence
from os import fspath
from typing import Any

import pyarrow as pa

from ..errors import ContainerError
from . import engine
from .collection import load_collection
from .query import Index, normalize_index
from .source import PathInput


def _scalar(query: str, arguments: list[object]) -> object:
    row = engine.open_reader().execute(query, arguments).fetchone()
    if row is None:
        raise ContainerError(f"the cozip extension returned no row for {arguments[0]!r}")
    return row[0]


def contract(path: PathInput) -> pa.Table:
    """Return the contract as rows of ``kind`` and ``value``."""
    return engine.open_reader().execute("SELECT * FROM taco_contract(?)", [fspath(path)]).to_arrow_table()


def _string_list(query: str, path: PathInput) -> list[str]:
    value = _scalar(query, [fspath(path)])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ContainerError(f"the cozip extension returned an invalid string list for {path!r}")
    return value


def structure(path: PathInput) -> list[str]:
    """Return ``taco:structure``, empty when the contract declares none."""
    return _string_list("SELECT taco_structure(?)", path)


def levels(path: PathInput) -> list[str]:
    """Return metadata levels, parents before children."""
    return _string_list("SELECT taco_levels(?)", path)


def derived(path: PathInput) -> dict[str, Any]:
    """Return serialized ``taco:derived`` declarations."""
    values = _string_list("SELECT taco_derived(?)", path)
    if not values:
        return {}
    if len(values) != 1:
        raise ContainerError(f"the cozip extension returned invalid taco:derived for {path!r}")
    try:
        data = json.loads(values[0])
    except json.JSONDecodeError as exc:
        raise ContainerError(f"the cozip extension returned invalid taco:derived for {path!r}") from exc
    if not isinstance(data, dict):
        raise ContainerError(f"the cozip extension returned invalid taco:derived for {path!r}")
    return data


def collection(path: PathInput) -> dict[str, object]:
    """Return parsed ``COLLECTION.json`` metadata."""
    return load_collection(path)


def _string_scalar(query: str, path: PathInput) -> str:
    value = _scalar(query, [fspath(path)])
    if not isinstance(value, str):
        raise ContainerError(f"the cozip extension returned an invalid string for {path!r}")
    return value


def profile(path: PathInput) -> str:
    """Return the CoZIP profile: ``none``, ``flat`` or ``taco``."""
    return _string_scalar("SELECT cozip_profile(?)", path)


def sql(
    path: PathInput,
    *,
    idx: Index = None,
    level: str | None = None,
    layout: str = "wide",
    files: Sequence[str] | None = None,
    location: bool = True,
) -> str:
    """Return the query ``read_taco()`` would run, for debugging."""
    if layout not in ("wide", "long"):
        raise ValueError("layout must be 'wide' or 'long'")
    if not isinstance(location, bool):
        raise TypeError("location must be a boolean")
    value = _scalar(
        "SELECT taco_sql(?, ?, ?, ?, ?, ?)",
        [fspath(path), normalize_index(idx), level, layout == "wide", None if files is None else list(files), location],
    )
    if not isinstance(value, str):
        raise ContainerError(f"the cozip extension returned invalid SQL for {path!r}")
    return value


__all__ = ["collection", "contract", "derived", "levels", "profile", "sql", "structure"]
