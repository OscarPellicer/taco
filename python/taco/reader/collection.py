from __future__ import annotations

import json
from collections.abc import Sequence
from os import fspath

from ..contract.collection import Collection, Extent
from ..errors import ContainerError
from . import engine
from .source import Location, PathInput


def _collection_dict(value: object, path: PathInput | Location) -> dict[str, object]:
    if not isinstance(value, (str, bytes, bytearray)):
        raise ContainerError(f"the cozip extension returned invalid COLLECTION.json for {path!r}")
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ContainerError(f"the cozip extension returned a non-object COLLECTION.json for {path!r}")
    return data


def load_collection(path: PathInput | Location) -> dict[str, object]:
    """Read and parse one ``COLLECTION.json`` document."""
    row = engine.open_reader().execute("SELECT taco_collection(?)", [fspath(path)]).fetchone()
    if row is None:
        raise ContainerError(f"the cozip extension returned no collection for {path!r}")
    return _collection_dict(row[0], path)


def load_collections(paths: Sequence[Location]) -> list[dict[str, object]]:
    """Read collection documents in the same order as their sources."""
    rows = (
        engine.open_reader()
        .execute(
            "SELECT taco_collection(path) FROM unnest(?::VARCHAR[]) WITH ORDINALITY AS sources(path, position) "
            "ORDER BY position",
            [[fspath(path) for path in paths]],
        )
        .fetchall()
    )
    if len(rows) != len(paths):
        raise ContainerError("the cozip extension did not return every COLLECTION.json")
    return [_collection_dict(row[0], path) for row, path in zip(rows, paths, strict=True)]


def merge_collections(paths: tuple[Location, ...]) -> Collection:
    """Validate compatible partitions and merge their collection extents."""
    collections = tuple(Collection.from_dict(data) for data in load_collections(paths))
    if len(collections) == 1:
        return collections[0]
    if any(collection.sources is not None for collection in collections):
        raise ContainerError("a source list cannot contain TACOCAT datasets")

    expected = collections[0].to_dict()
    expected.pop("extent", None)
    expected.pop("taco:sources", None)
    for path, collection in zip(paths[1:], collections[1:], strict=True):
        actual = collection.to_dict()
        actual.pop("extent", None)
        actual.pop("taco:sources", None)
        if collection.contract.levels != collections[0].contract.levels or actual != expected:
            raise ContainerError(f"source does not belong to the same collection: {path}")

    extents = [collection.extent for collection in collections if collection.extent is not None]
    return collections[0].replace(extent=Extent.union(extents))


__all__ = ["load_collection", "load_collections", "merge_collections"]
