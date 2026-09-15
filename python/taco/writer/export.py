from __future__ import annotations

from collections.abc import Iterator, Sequence
from os import PathLike
from pathlib import Path
from typing import Any, TypeAlias

import pyarrow as pa

from ..container.view import DatasetView, open_view
from ..contract.contract import SAMPLE_LEVEL, Contract
from ..contract.naming import DATA_DIR, OFFSET, RELATIVE_PATH, SIZE, SOURCE_FILE, level_folder
from ..contract.sample import _PreparedAsset, _PreparedNode, _PreparedSample
from ..errors import ContainerError
from ..reader import engine
from ..reader.dataset import Dataset
from ..reader.manifest import resolve_dataset
from ..reader.query import Index, read_table
from ..reader.source import Source
from .api import open_writer
from .base import BuildResult

# Sample ids restart in every TACOCAT partition, so the partition is part of
# the key. It is None for FOLDER and ZIP datasets.
SampleKey: TypeAlias = tuple[str | None, int]

_CHUNK_SIZE = 1024 * 1024


def export(
    source: Source | Dataset,
    output: str | PathLike[str],
    *,
    where: str | None = None,
    idx: Index = None,
    id: str | None = None,
    description: str | None = None,
    dataset_version: str | None = None,
    title: str | None = None,
    keywords: Sequence[str] | None = None,
    overwrite: bool = False,
    progress: bool = False,
) -> BuildResult:
    """Write the selected samples of a local dataset as a new dataset.

    ``where`` is a SQL condition on the rows of ``taco.read()`` and ``idx``
    selects sample positions as it does there. The output keeps the contract,
    numbers its samples from 0 and recomputes the extent. A subset needs its
    own ``id`` and ``description``. Without a selection every sample is
    copied, which turns a FOLDER into a ZIP or a TACOCAT into one dataset.
    """
    sources = source.sources if isinstance(source, Dataset) else resolve_dataset(source).sources
    if len(sources) != 1 or not isinstance(sources[0], Path):
        raise ValueError("export reads one local dataset")
    dataset = open_view(sources[0])

    selected = None
    if where is not None or idx is not None:
        if id is None or id == dataset.collection.id or description is None:
            raise ValueError("a subset needs its own id and description")
        selected = _select(dataset.path, where, idx)

    changes = {
        "id": id,
        "description": description,
        "dataset_version": dataset_version,
        "title": title,
        "keywords": keywords,
    }
    collection = dataset.collection.replace(
        sources=None,
        **{name: value for name, value in changes.items() if value is not None},
    )

    with open_writer(collection, output, overwrite=overwrite, progress=progress) as writer:
        total = dataset.sample_count if selected is None else len(selected)
        with writer._show_progress(total, f"reading {dataset.path.name}") as bar:
            for sample in _samples(dataset, selected, writer._stage / "export"):
                writer._add_prepared(sample)
                bar.update()
        return writer.run()


def _select(path: Path, where: str | None, idx: Index) -> set[SampleKey]:
    # The condition sees the same columns as taco.read(), evaluated by the
    # reader connection so timestamps compare in UTC.
    table = read_table(path, idx=idx, location=False)
    if where is not None:
        table = engine.open_reader().from_arrow(table).filter(where).to_arrow_table()
    samples = table.column("sample_id").to_pylist()
    if "source_file" not in table.column_names:
        return {(None, sample) for sample in samples}
    return set(zip(table.column("source_file").to_pylist(), samples, strict=True))


def _samples(dataset: DatasetView, selected: set[SampleKey] | None, stage: Path) -> Iterator[_PreparedSample]:
    contract = dataset.contract
    nodes: dict[SampleKey, dict[str, list[_PreparedNode]]] = {}
    files: dict[SampleKey, list[dict[str, Any]]] = {}
    for level in contract.levels[1:]:
        folder = level_folder(level)
        for key, row in _rows(dataset.level(level), selected):
            name = row[RELATIVE_PATH].rsplit("/", 1)[1]
            is_folder = contract.is_folder(folder, name)
            node = _PreparedNode(name, is_folder, _metadata(contract, level, row))
            nodes.setdefault(key, {}).setdefault(level, []).append(node)
            if not is_folder:
                files.setdefault(key, []).append(row)

    # Rows keep the order of the source. The writer derives the new ids and
    # relative paths from that order, so only the data has to be located.
    for index, (key, row) in enumerate(_rows(dataset.level(SAMPLE_LEVEL), selected)):
        metadata = _metadata(contract, SAMPLE_LEVEL, row)
        if contract.is_null:
            asset = _PreparedAsset(_payload(dataset, row, stage / str(index)), None)
            yield _PreparedSample((asset,), metadata, {})
            continue

        assets = []
        for child in files.pop(key, []):
            path = child[RELATIVE_PATH].split("/", 1)[1]
            assets.append(_PreparedAsset(_payload(dataset, child, stage / str(index) / path), path))
        levels = nodes.pop(key, {})
        rows = {level: tuple(levels.get(level, ())) for level in contract.levels[1:]}
        yield _PreparedSample(tuple(assets), metadata, rows)


def _rows(table: pa.Table, selected: set[SampleKey] | None) -> Iterator[tuple[SampleKey, dict[str, Any]]]:
    for batch in table.to_batches():
        for row in batch.to_pylist():
            # Every relative path starts with the index of its sample.
            key = row.get(SOURCE_FILE), int(row[RELATIVE_PATH].split("/", 1)[0])
            if selected is None or key in selected:
                yield key, row


def _metadata(contract: Contract, level: str, row: dict[str, Any]) -> dict[str, Any]:
    return {name: row[name] for name in contract.metadata[level]}


def _payload(dataset: DatasetView, row: dict[str, Any], target: Path) -> Path:
    relative_path: str = row[RELATIVE_PATH]
    if dataset.container == "folder":
        return dataset.path / DATA_DIR / relative_path

    # A TACOCAT row points into its partition, which lives beside the catalog.
    archive = dataset.path if dataset.container == "zip" else dataset.path.parent / row[SOURCE_FILE]
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("rb") as stream, target.open("wb") as copy:
        stream.seek(row[OFFSET])
        remaining = row[SIZE]
        while remaining:
            chunk = stream.read(min(remaining, _CHUNK_SIZE))
            if not chunk:
                raise ContainerError(f"{archive} ends inside {relative_path}")
            copy.write(chunk)
            remaining -= len(chunk)
    return target


__all__ = ["export"]
