from __future__ import annotations

from dataclasses import dataclass
from os import fspath
from pathlib import Path
from typing import Any

from . import native
from .source import Location, Source, normalize_sources


@dataclass(frozen=True)
class DatasetResolution:
    sources: tuple[Location, ...]
    collection: dict[str, Any] | None = None
    version: str | None = None
    versions: tuple[str, ...] = ()
    manifest: Location | None = None


def _location(value: str) -> Location:
    return value if "://" in value else Path(value).resolve()


def manifest_candidate(source: Location) -> Location | None:
    candidate = native.manifest_candidate(source)
    if candidate is None:
        return None
    return Path(candidate) if isinstance(source, Path) else candidate


def join_manifest_href(candidate: Location, href: str) -> Location:
    return _location(native.join_manifest_href(fspath(candidate), href))


def resolve_dataset(source: Source) -> DatasetResolution:
    paths = normalize_sources(source)
    if len(paths) != 1:
        return DatasetResolution(paths)

    resolution = native.resolve(paths[0])
    manifest = resolution["manifest"]
    if manifest is None:
        return DatasetResolution(paths)
    return DatasetResolution(
        (_location(resolution["source"]),),
        collection=resolution["collection"],
        version=resolution["version"],
        versions=tuple(resolution["versions"]),
        manifest=manifest if isinstance(paths[0], str) else Path(manifest),
    )


__all__ = [
    "DatasetResolution",
    "join_manifest_href",
    "manifest_candidate",
    "resolve_dataset",
]
