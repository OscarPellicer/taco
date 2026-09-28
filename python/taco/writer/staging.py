from __future__ import annotations

import pickle
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class StagedSamples(Generic[T]):
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = path.open("ab")
        self._count = 0

    @property
    def count(self) -> int:
        return self._count

    def append(self, item: T) -> None:
        pickle.dump(item, self._file, protocol=pickle.HIGHEST_PROTOCOL)
        self._count += 1

    def close(self) -> None:
        if not self._file.closed:
            self._file.flush()
            self._file.close()

    def __iter__(self) -> Iterator[T]:
        if not self._file.closed:
            self._file.flush()
        return read_staged(self.path)


def read_staged(path: Path) -> Iterator[Any]:
    # Each pass opens its own handle, so partitions can be read concurrently.
    with path.open("rb") as stream:
        while True:
            try:
                yield pickle.load(stream)
            except EOFError:
                return


__all__ = ["StagedSamples", "read_staged"]
