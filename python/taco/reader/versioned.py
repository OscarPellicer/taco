from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

from .._source import Location, Source, normalize
from ..contract.collection import SEMVER
from ..errors import ContainerError


@dataclass(frozen=True)
class Resolution:
    sources: tuple[Location, ...]
    collection: dict[str, Any] | None = None
    version: str | None = None
    versions: tuple[str, ...] = ()
    manifest: Location | None = None


def _direct(name: str) -> bool:
    return name == ".tacocat" or name.lower().endswith(".zip") or SEMVER.fullmatch(name) is not None


def _candidate(source: Location) -> Location | None:
    if isinstance(source, Path):
        if source.name == "taco.json":
            return source
        if _direct(source.name):
            return None
        candidate = source / "taco.json"
        return candidate if candidate.is_file() else None

    parsed = urlsplit(source)
    name = PurePosixPath(parsed.path).name
    if name == "taco.json":
        return source
    if _direct(name):
        return None
    return urljoin(source.rstrip("/") + "/", "taco.json")


def _read(candidate: Location, *, required: bool) -> bytes | None:
    if isinstance(candidate, Path):
        try:
            return candidate.read_bytes()
        except FileNotFoundError as error:
            if not required:
                return None
            raise ContainerError(f"versioned manifest does not exist: {candidate}") from error
        except OSError as error:
            raise ContainerError(f"could not read versioned manifest {candidate}: {error}") from error

    try:
        with urlopen(candidate) as response:
            return cast(bytes, response.read())
    except HTTPError as error:
        if error.code == 404 and not required:
            return None
        raise ContainerError(f"could not read versioned manifest {candidate}: HTTP {error.code}") from error
    except URLError as error:
        raise ContainerError(f"could not read versioned manifest {candidate}: {error.reason}") from error


def _object(value: object, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ContainerError(f"{context} must be an object")
    return value


def _parse(payload: bytes, candidate: Location) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContainerError(f"versioned manifest is not valid JSON: {candidate}") from error
    manifest = _object(value, context="versioned manifest")
    if manifest.get("taco:container") != "versioned":
        raise ContainerError("taco:container must be 'versioned'")
    return manifest


def _join(candidate: Location, href: str) -> Location:
    if "://" in href:
        return href
    if isinstance(candidate, Path):
        return (candidate.parent / href).resolve()
    return urljoin(candidate, href)


def resolve(source: Source) -> Resolution:
    paths = normalize(source)
    if len(paths) != 1:
        return Resolution(paths)

    original = paths[0]
    explicit_manifest = (isinstance(original, Path) and original.name == "taco.json") or (
        isinstance(original, str) and PurePosixPath(urlsplit(original).path).name == "taco.json"
    )
    candidate = _candidate(original)
    if candidate is None:
        return Resolution(paths)

    payload = _read(candidate, required=explicit_manifest)
    if payload is None:
        return Resolution(paths)
    manifest = _parse(payload, candidate)
    versions = _object(manifest.get("taco:versions"), context="taco:versions")
    if not versions:
        raise ContainerError("taco:versions must contain at least one version")

    selected = manifest.get("taco:default_version")
    if not isinstance(selected, str) or not selected:
        raise ContainerError("taco:default_version must be a non-empty string")
    if selected not in versions:
        raise ContainerError(f"taco:default_version {selected!r} is not present in taco:versions")

    entries: dict[str, tuple[str, dict[str, Any]]] = {}
    for version, value in versions.items():
        if SEMVER.fullmatch(version) is None:
            raise ContainerError(f"taco:versions key {version!r} must follow Semantic Versioning")
        entry = _object(value, context=f"version {version!r}")
        href = entry.get("href")
        if not isinstance(href, str) or not href:
            raise ContainerError(f"version {version!r} needs a non-empty href")
        collection = _object(entry.get("collection"), context=f"version {version!r} collection")
        dataset_version = collection.get("dataset_version")
        if dataset_version != version:
            raise ContainerError(f"version {version!r} embeds collection dataset_version {dataset_version!r}")
        entries[version] = (href, collection)

    href, collection = entries[selected]

    return Resolution(
        (_join(candidate, href),),
        collection=collection,
        version=selected,
        versions=tuple(versions),
        manifest=candidate,
    )


__all__ = ["Resolution", "resolve"]
