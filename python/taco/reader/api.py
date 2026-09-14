from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import pyarrow as pa

from .dataset import Dataset
from .manifest import resolve_dataset
from .query import Index, read_table
from .source import Source

Layout = Literal["wide", "long"]


def open_dataset(source: Source) -> Dataset:
    """Open a TACO dataset, collection root, archive, folder, or catalog."""
    return Dataset(source)


def read(
    source: Source | Dataset,
    *,
    layout: Layout = "wide",
    idx: Index = None,
    level: str | None = None,
    files: Sequence[str] | None = None,
    location: bool = True,
) -> pa.Table:
    """Read dataset metadata in wide or long layout."""
    if layout not in ("wide", "long"):
        raise ValueError("layout must be 'wide' or 'long'")
    if isinstance(source, Dataset):
        sources = source.sources
    else:
        sources = resolve_dataset(source).sources
        if len(sources) > 1:
            sources = open_dataset(sources).sources
    return read_table(
        sources,
        idx=idx,
        level=level,
        pivoted=layout == "wide",
        files=files,
        location=location,
    )


__all__ = ["Dataset", "Layout", "open_dataset", "read"]
