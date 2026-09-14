from __future__ import annotations

from collections.abc import Sequence
from os import fspath

import pyarrow as pa

from . import engine
from .source import Location, PathInput, Source, normalize_sources, source_labels

__all__ = ["Index", "build_read_query", "read_table"]


Index = int | Sequence[int] | None

_LOCATION_COLUMN = "taco:location"
_LEGACY_LOCATION_COLUMN = "cozip:gdal_vsi"


def _text(path: PathInput | Location) -> str:
    return fspath(path)


def normalize_index(value: Index) -> str | None:
    """``read_taco`` takes idx as an integer or a two-element range."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("idx must be an integer or a two-element range")
    if isinstance(value, int):
        return str(value)
    values = list(value)
    if len(values) != 2 or not all(isinstance(item, int) and not isinstance(item, bool) for item in values):
        raise TypeError("idx must be an integer or a two-element range")
    return f"[{values[0]}, {values[1]}]"


def _legacy_taco_signature(message: str) -> bool:
    return "read_taco" in message and "gdal_vsi" in message and "does not support the supplied arguments" in message


def build_read_query(paths: tuple[Location, ...], *, level: str | None, location_argument: str) -> str:
    call = f"read_taco(?, idx := ?, level := ?, pivoted := ?, files := ?, {location_argument} := ?)"
    if len(paths) == 1:
        return f"SELECT * FROM {call}"
    projection = (
        "?::VARCHAR AS source_file, taco.*"
        if level is not None
        else "taco.sample_id, ?::VARCHAR AS source_file, taco.* EXCLUDE (sample_id)"
    )
    branch = f"SELECT {projection} FROM {call} AS taco"
    return " UNION ALL BY NAME ".join(branch for _ in paths)


def _read_arguments(paths: tuple[Location, ...], options: Sequence[object]) -> list[object]:
    if len(paths) == 1:
        return [_text(paths[0]), *options]
    arguments: list[object] = []
    for label, source in zip(source_labels(paths), paths, strict=True):
        arguments.extend([label, _text(source), *options])
    return arguments


def _normalize_locations(
    table: pa.Table,
    *,
    location: bool,
    level: str | None,
    pivoted: bool,
    legacy: bool,
) -> pa.Table:
    names = set(table.column_names)
    preserve_current = not legacy and location and level is None and not pivoted
    drop = {"cozip:location"} & names
    if _LOCATION_COLUMN in names and not preserve_current:
        drop.add(_LOCATION_COLUMN)
    if _LEGACY_LOCATION_COLUMN in names and (not legacy or not location or level is not None or pivoted):
        drop.add(_LEGACY_LOCATION_COLUMN)
    if drop:
        table = table.drop(sorted(drop))
    if legacy and location and level is None and not pivoted and _LEGACY_LOCATION_COLUMN in table.column_names:
        table = table.rename_columns(
            [_LOCATION_COLUMN if name == _LEGACY_LOCATION_COLUMN else name for name in table.column_names]
        )
    return table


def read_table(
    path: Source,
    *,
    idx: Index = None,
    level: str | None = None,
    pivoted: bool = True,
    files: Sequence[str] | None = None,
    location: bool = True,
) -> pa.Table:
    """Read a dataset through ``read_taco()``.

    ``path`` is a ``.zip`` archive, a FOLDER directory, a ``.tacocat``
    catalog or a sequence of compatible partitions. Multiple paths are
    combined by DuckDB and include ``source_file`` in the result. ``idx``
    selects local sample positions in every source. ``level`` returns one
    contract level raw, with its internal columns. ``pivoted`` gives one row
    per sample with a column per file; ``False`` gives one row per file.
    ``files`` restricts which structure leaves become columns. ``location``
    fills the file columns in a pivoted read and adds ``taco:location`` to a
    non-pivoted read. Raw level reads never synthesize a location column.
    """
    paths = normalize_sources(path)
    if not isinstance(location, bool):
        raise TypeError("location must be a boolean")
    options: list[object] = [normalize_index(idx), level, pivoted, None if files is None else list(files), location]
    arguments = _read_arguments(paths, options)
    connection = engine.open_reader()
    legacy = False
    try:
        result = connection.execute(build_read_query(paths, level=level, location_argument="location"), arguments)
    except Exception as exc:
        if not _legacy_taco_signature(str(exc)):
            raise
        legacy = True
        result = connection.execute(build_read_query(paths, level=level, location_argument="gdal_vsi"), arguments)
    return _normalize_locations(result.to_arrow_table(), location=location, level=level, pivoted=pivoted, legacy=legacy)
