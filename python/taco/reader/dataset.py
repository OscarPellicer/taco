from __future__ import annotations

from ..contract.collection import Collection
from ..contract.contract import Contract
from ..errors import CollectionError, ContainerError
from .collection import merge_collections
from .manifest import resolve_dataset
from .source import Source


class Dataset:
    def __init__(self, source: Source) -> None:
        resolution = resolve_dataset(source)
        self.sources = resolution.sources
        if resolution.collection is None:
            self.collection = merge_collections(self.sources)
        else:
            try:
                self.collection = Collection.from_dict(resolution.collection)
            except CollectionError as error:
                raise ContainerError(f"version {resolution.version!r} embeds an invalid collection: {error}") from error
        self.version = resolution.version or self.collection.dataset_version
        self.versions = resolution.versions
        self.manifest = resolution.manifest

    @property
    def contract(self) -> Contract:
        return self.collection.contract

    def __repr__(self) -> str:
        location = f"source={self.sources[0]!r}" if len(self.sources) == 1 else f"sources={len(self.sources)}"
        return f"Dataset({self.collection.id!r}, version={self.collection.dataset_version!r}, {location})"

    def _repr_html_(self) -> str:
        from .._repr import dataset_html

        return dataset_html(self)


__all__ = ["Dataset"]
