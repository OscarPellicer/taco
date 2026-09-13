from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from . import extensions, metadata, reader
from .contract import Asset, Collection, Contract, Folder, Sample
from .dataset import Dataset, open_dataset, read
from .errors import TacoError
from .metadata._base import ExtensionContext
from .schema import CollectionMetadata, DerivedMetadata, Extension, Level, Metadata, MetadataSchema
from .tacocat import consolidate
from .validate import validate
from .writer import open_writer

try:
    __version__ = version("taco-eo")
except PackageNotFoundError:  # pragma: no cover - source checkout
    __version__ = "0.0.0+unknown"

__all__ = [
    "Asset",
    "Collection",
    "CollectionMetadata",
    "Contract",
    "Dataset",
    "DerivedMetadata",
    "Extension",
    "ExtensionContext",
    "Folder",
    "Level",
    "Metadata",
    "MetadataSchema",
    "Sample",
    "TacoError",
    "__version__",
    "consolidate",
    "extensions",
    "metadata",
    "open_dataset",
    "open_writer",
    "read",
    "reader",
    "validate",
]
