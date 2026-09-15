from __future__ import annotations

from collections.abc import Sequence

import pyarrow as pa

from . import engine, native
from .source import Source, normalize_sources

__all__ = ["Index", "build_sql", "read_table"]


Index = int | Sequence[int] | None


def normalize_index(value: Index) -> str | None:
    """The core takes idx as an integer or a two-element range."""
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


def build_sql(
    path: Source,
    *,
    idx: Index = None,
    level: str | None = None,
    pivoted: bool = True,
    files: Sequence[str] | None = None,
    location: bool = True,
) -> str:
    """The query that reads ``path``, with the metadata copied into the cache."""
    if not isinstance(location, bool):
        raise TypeError("location must be a boolean")
    index = normalize_index(idx)
    datasets = [native.NativeDataset(source) for source in normalize_sources(path)]
    return native.sql(
        datasets,
        idx=index,
        level=level,
        pivoted=pivoted,
        files=None if files is None else list(files),
        location=location,
    )


def read_table(
    path: Source,
    *,
    idx: Index = None,
    level: str | None = None,
    pivoted: bool = True,
    files: Sequence[str] | None = None,
    location: bool = True,
) -> pa.Table:
    """Read a dataset.

    ``path`` is a ``.zip`` archive, a FOLDER directory, a ``.tacocat``
    catalog or a sequence of compatible partitions, local or remote. Multiple
    paths are combined and include ``source_file`` in the result. ``idx``
    selects local sample positions in every source. ``level`` returns one
    contract level raw, with its internal columns. ``pivoted`` gives one row
    per sample with a column per file; ``False`` gives one row per file.
    ``files`` restricts which structure leaves are read. ``location`` fills
    the file columns in a pivoted read and adds ``taco:location`` to a
    non-pivoted read. Raw level reads never synthesize a location column.
    """
    query = build_sql(path, idx=idx, level=level, pivoted=pivoted, files=files, location=location)
    return engine.open_reader().execute(query).to_arrow_table()
