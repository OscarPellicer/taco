from __future__ import annotations

import zipfile
from pathlib import Path

import pyarrow as pa
import pytest

import taco
from taco.container.view import DatasetView, open_view
from taco.contract.types import type_name
from taco.errors import WriterError

from .datasets import CASES, DatasetCase, case_id
from .test_writer_cases import data_files, write_case


def assert_same_dataset(expected: DatasetView, actual: DatasetView) -> None:
    assert actual.collection_json == expected.collection_json
    assert actual.levels == expected.levels
    for level in expected.levels:
        table = expected.level(level)
        exported = actual.level(level)
        assert exported.schema.metadata == table.schema.metadata
        exported = exported.select(table.column_names)
        assert [describe(field) for field in exported.schema] == [describe(field) for field in table.schema]
        assert exported.to_pylist() == table.to_pylist()


def describe(field: pa.Field) -> tuple[object, ...]:
    # COLLECTION.json names a struct type without the nullability of its
    # children, so a dataset written from it matches the contract by name.
    return field.name, type_name(field.type), field.nullable, field.metadata


@pytest.mark.parametrize("case", CASES, ids=case_id)
def test_export_copies_every_case(case: DatasetCase, tmp_path: Path) -> None:
    direct_path = tmp_path / "direct"
    archive_path = tmp_path / "source.zip"
    write_case(case, direct_path)
    write_case(case, archive_path)

    exported_path = tmp_path / "exported"
    result = taco.export(archive_path, exported_path)

    assert result.samples == len(case.samples)
    assert taco.validate(exported_path).ok
    assert_same_dataset(open_view(direct_path), open_view(exported_path))
    assert data_files(exported_path) == data_files(direct_path)

    repacked_path = tmp_path / "repacked.zip"
    taco.export(exported_path, repacked_path)
    assert taco.validate(repacked_path).ok
    assert_same_dataset(open_view(direct_path), open_view(repacked_path))


def test_export_subset_matches_direct_write(
    archive: Path, tmp_path: Path, collection: taco.Collection, make_sample
) -> None:
    subset = collection.replace(id="tiny-change-val", description="Validation samples")
    direct = tmp_path / "direct"
    with taco.open_writer(subset, direct) as writer:
        writer.extend([make_sample(1, 1), make_sample(3, 0)])
        writer.run()

    output = tmp_path / "val"
    result = taco.export(
        archive,
        output,
        where="\"ml:split\" = 'val'",
        id="tiny-change-val",
        description="Validation samples",
    )

    assert result.samples == 2
    assert taco.validate(output).ok
    assert_same_dataset(open_view(direct), open_view(output))
    assert data_files(output) == data_files(direct)


def test_export_subset_to_zip(archive: Path, tmp_path: Path) -> None:
    output = tmp_path / "middle.zip"
    taco.export(
        taco.open_dataset(archive),
        output,
        idx=(1, 3),
        id="tiny-change-middle",
        description="Second and third samples",
        dataset_version="1.0.1",
    )

    dataset = open_view(output)
    assert taco.validate(output).ok
    assert dataset.collection.dataset_version == "1.0.1"
    assert dataset.level("sample").column("ml:cloud_cover").to_pylist() == [10.5, 21.0]
    with zipfile.ZipFile(output) as archive_file:
        assert archive_file.read("DATA/0/mask.tif") == b"1:mask.tif"
        assert archive_file.read("DATA/1/extra1.png") == b"2:extra1.png"


def test_export_tacocat(tmp_path: Path, collection: taco.Collection, make_sample) -> None:
    with taco.open_writer(collection, tmp_path / "parts" / "dataset.zip", partition_size=1) as writer:
        writer.extend(make_sample(index) for index in range(4))
        catalog = writer.run().path

    merged = tmp_path / "merged"
    taco.export(catalog, merged)
    assert taco.validate(merged).ok
    assert open_view(merged).sample_count == 4
    assert "taco:sources" not in open_view(merged).collection_json

    train = tmp_path / "train.zip"
    taco.export(catalog, train, where="\"ml:split\" = 'train'", id="tiny-change-train", description="Training samples")
    dataset = open_view(train)
    assert taco.validate(train).ok
    assert dataset.level("sample").column("ml:cloud_cover").to_pylist() == [0.0, 21.0]
    with zipfile.ZipFile(train) as archive_file:
        assert archive_file.read("DATA/1/mask.tif") == b"2:mask.tif"


def test_subset_needs_its_own_identity(archive: Path, tmp_path: Path) -> None:
    output = tmp_path / "subset.zip"
    with pytest.raises(ValueError, match="own id and description"):
        taco.export(archive, output, idx=0)
    with pytest.raises(ValueError, match="own id and description"):
        taco.export(archive, output, idx=0, id="tiny-change", description="Same id")
    with pytest.raises(ValueError, match="own id and description"):
        taco.export(archive, output, idx=0, id="tiny-change-0")
    with pytest.raises(WriterError, match="without samples"):
        taco.export(archive, output, where="false", id="tiny-change-none", description="Nothing")
    assert not output.exists()


def test_export_reads_one_local_dataset(archive: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="one local dataset"):
        taco.export([archive, tmp_path / "other.zip"], tmp_path / "out.zip")
    with pytest.raises(ValueError, match="one local dataset"):
        taco.export("https://example.com/dataset.zip", tmp_path / "out.zip")
