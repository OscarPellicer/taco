from __future__ import annotations

from collections.abc import Sequence

import pyarrow as pa

from .dataset import Dataset
from .source import Source


def open_dataset(source: Source) -> Dataset:
    """Open a local or remote TACO dataset."""
    return Dataset(source)


def read(
    source: Source | Dataset,
    *,
    files: str | Sequence[str] | None = None,
) -> pa.Table:
    """Read all samples as a wide Arrow table."""
    dataset = source if isinstance(source, Dataset) else open_dataset(source)
    return dataset.read(files=files)


__all__ = ["Dataset", "open_dataset", "read"]
