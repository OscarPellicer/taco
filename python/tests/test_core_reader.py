"""Read semantics of the native core, from the joins to the error messages."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Annotated

import pyarrow as pa
import pytest
from pydantic import BaseModel

import taco
from taco.errors import ContainerError


class Split(BaseModel):
    split: str
    n_images: Annotated[int, pa.int32()]


class Kind(BaseModel):
    kind: str


class Raster(BaseModel):
    resolution: Annotated[int, pa.int32()]


def payload(tag: str, index: int) -> bytes:
    return f"{tag}-{index}:".encode() * 40


def collection(name: str, contract: taco.Contract) -> taco.Collection:
    return taco.Collection(
        contract=contract,
        id=name,
        dataset_version="1.0.0",
        description=name,
        licenses=["MIT"],
        providers=[{"name": "TACO tests"}],
        tasks=["other"],
    )


def write(name: str, contract: taco.Contract, samples: list[taco.Sample], output: Path, **options) -> Path:
    with taco.open_writer(collection(name, contract), output, **options) as writer:
        writer.extend(samples)
        return writer.run().path


def nested_samples() -> list[taco.Sample]:
    return [
        taco.Sample(
            metadata=taco.Metadata(ml=Split(split="train" if index % 2 == 0 else "val", n_images=index)),
            folders=[
                taco.Folder("before", metadata=taco.Metadata(node=Kind(kind="imagery"))),
                taco.Folder("after", metadata=taco.Metadata(node=Kind(kind="imagery"))),
            ],
            assets=[
                taco.Asset(
                    payload("b02", index), path="before/B02.bin", metadata=taco.Metadata(raster=Raster(resolution=10))
                ),
                taco.Asset(
                    payload("b03", index), path="before/B03.bin", metadata=taco.Metadata(raster=Raster(resolution=10))
                ),
                taco.Asset(
                    payload("a02", index), path="after/B02.bin", metadata=taco.Metadata(raster=Raster(resolution=20))
                ),
                taco.Asset(
                    payload("change", index), path="change.bin", metadata=taco.Metadata(node=Kind(kind="label"))
                ),
            ],
        )
        for index in range(3)
    ]


NESTED = taco.Contract(
    structure=["before/B02.bin", "before/B03.bin", "after/B02.bin", "change.bin"],
    metadata=taco.MetadataSchema(
        taco.Level("sample", ml=Split),
        taco.Level("children", node=Kind),
        taco.Level("children/before", raster=Raster),
        taco.Level("children/after", raster=Raster),
    ),
)


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("core-reader")
    write("nested", NESTED, nested_samples(), root / "nested.zip")
    write("nested", NESTED, nested_samples(), root / "nested")

    variable = taco.Contract(
        structure=["img*[0,3].bin", "mask.bin"],
        metadata=taco.MetadataSchema(taco.Level("sample", ml=Split), taco.Level("children", node=Kind)),
    )
    samples = []
    for index in range(3):
        assets = [
            taco.Asset(
                payload(f"img{number}", index), path=f"img{number}.bin", metadata=taco.Metadata(node=Kind(kind="image"))
            )
            for number in range(index)
        ]
        assets.append(
            taco.Asset(payload("mask", index), path="mask.bin", metadata=taco.Metadata(node=Kind(kind="label")))
        )
        samples.append(taco.Sample(metadata=taco.Metadata(ml=Split(split="train", n_images=index)), assets=assets))
    write("variable", variable, samples, root / "variable.zip")

    shadow = taco.Contract(
        structure=["before/B02.bin", "change.bin"],
        metadata=taco.MetadataSchema(
            taco.Level("sample", ml=Split),
            taco.Level("children", raster=Raster),
            taco.Level("children/before", raster=Raster),
        ),
    )
    samples = [
        taco.Sample(
            metadata=taco.Metadata(ml=Split(split="train", n_images=1)),
            folders=[taco.Folder("before", metadata=taco.Metadata(raster=Raster(resolution=1)))],
            assets=[
                taco.Asset(
                    payload("b02", index), path="before/B02.bin", metadata=taco.Metadata(raster=Raster(resolution=3))
                ),
                taco.Asset(
                    payload("change", index), path="change.bin", metadata=taco.Metadata(raster=Raster(resolution=2))
                ),
            ],
        )
        for index in range(2)
    ]
    write("shadow", shadow, samples, root / "shadow.zip")

    null = taco.Contract(structure=None, metadata=taco.MetadataSchema(taco.Level("sample", ml=Split)))
    samples = [
        taco.Sample(assets=payload("sample", index), metadata=taco.Metadata(ml=Split(split="train", n_images=index)))
        for index in range(6)
    ]
    write("null", null, samples, root / "null.zip")

    (root / "catalog").mkdir()
    write("nested", NESTED, nested_samples(), root / "catalog" / "part.zip", partition_by="ml:split")
    return root


def by_sample(table: pa.Table) -> list[dict]:
    return sorted(
        table.to_pylist(), key=lambda row: (row.get("source_file") or "", row["sample_id"], row.get("path") or "")
    )


def test_long_rows_carry_their_own_and_ancestor_metadata(data: Path) -> None:
    table = taco.read(data / "nested.zip", layout="long")
    assert table.num_rows == 12
    first = [row for row in by_sample(table) if row["sample_id"] == 0]
    assert [(row["path"], row["node:kind"], row["raster:resolution"]) for row in first] == [
        ("after/B02.bin", "imagery", 20),
        ("before/B02.bin", "imagery", 10),
        ("before/B03.bin", "imagery", 10),
        ("change.bin", "label", None),
    ]
    assert all(row["ml:split"] == "train" for row in first)


def test_wide_rows_have_a_location_per_leaf(data: Path) -> None:
    table = taco.read(data / "nested.zip")
    assert table.num_rows == 3
    row = by_sample(table)[0]
    assert row["before/B02.bin"].startswith("/vsisubfile/")
    assert row["before/B02.bin"].endswith(str((data / "nested.zip").resolve()))
    assert taco.read(data / "nested.zip", location=False).column("change.bin").null_count == 3


def test_files_idx_and_level(data: Path) -> None:
    path = data / "nested.zip"
    assert taco.read(path, files=["change.bin"]).column_names[-1] == "change.bin"
    assert "before/B02.bin" not in taco.read(path, files=["change.bin"]).column_names
    assert set(taco.read(path, layout="long", files=["change.bin"]).column("path").to_pylist()) == {"change.bin"}
    assert taco.read(path, idx=1).column("sample_id").to_pylist() == [1]
    assert sorted(taco.read(path, idx=(1, 3)).column("sample_id").to_pylist()) == [1, 2]

    level = taco.read(path, level="children/before")
    assert level.num_rows == 6
    assert sorted(level.column("internal:relative_path").to_pylist())[0] == "0/before/B02.bin"


def test_variable_leaves_are_ordered_lists(data: Path) -> None:
    path = data / "variable.zip"
    rows = by_sample(taco.read(path))
    assert [(row["ml:n_images"], len(row["img"])) for row in rows] == [(0, 0), (1, 1), (2, 2)]
    long = taco.read(path, layout="long")
    first_image = next(
        row["taco:location"] for row in long.to_pylist() if row["sample_id"] == 2 and row["path"] == "img0.bin"
    )
    assert rows[2]["img"][0] == first_image
    assert taco.read(path, location=False).column("img").null_count == 3


def test_a_redeclared_field_takes_the_deepest_value(data: Path) -> None:
    rows = by_sample(taco.read(data / "shadow.zip", layout="long"))
    assert [(row["sample_id"], row["path"], row["raster:resolution"]) for row in rows] == [
        (0, "before/B02.bin", 3),
        (0, "change.bin", 2),
        (1, "before/B02.bin", 3),
        (1, "change.bin", 2),
    ]


def test_single_file_samples(data: Path) -> None:
    table = taco.read(data / "null.zip")
    assert table.num_rows == 6
    assert all(value.startswith("/vsisubfile/") for value in table.column("taco:location").to_pylist())
    with pytest.raises(ContainerError, match="files requires taco:structure"):
        taco.read(data / "null.zip", files=["change.bin"])


def test_folder_and_catalog_locations(data: Path) -> None:
    folder = by_sample(taco.read(data / "nested"))
    assert folder[0]["change.bin"] == f"{(data / 'nested').resolve()}/DATA/0/change.bin"
    assert taco.read(data / "nested", layout="long").num_rows == 12

    catalog = taco.read(data / "catalog" / ".tacocat")
    assert catalog.num_rows == 3
    assert set(catalog.column("source_file").to_pylist()) == {"part_train.zip", "part_val.zip"}
    locations = catalog.column("change.bin").to_pylist()
    assert all(value.split(",", 1)[1].startswith(str((data / "catalog").resolve()) + "/part_") for value in locations)


def test_contract_errors(data: Path, tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    shutil.copytree(data / "nested", broken)
    (broken / "COLLECTION.json").write_text("{ not json")
    with pytest.raises(ContainerError, match=r"COLLECTION\.json is not valid JSON"):
        taco.read(broken, level="sample")

    old = tmp_path / "old"
    shutil.copytree(data / "nested", old)
    document = json.loads((old / "COLLECTION.json").read_text())
    document["taco:version"] = "2.0.0"
    (old / "COLLECTION.json").write_text(json.dumps(document))
    with pytest.raises(ContainerError, match="unsupported TACO version"):
        taco.reader.inspect.levels(old)

    with pytest.raises(ContainerError, match="files does not apply when level is set"):
        taco.read(data / "nested.zip", level="children", files=["change.bin"])


@pytest.mark.skipif(
    os.environ.get("TACO_TEST_REMOTE") != "1",
    reason="set TACO_TEST_REMOTE=1 to read from Hugging Face and Source Coop",
)
def test_remote_datasets() -> None:
    base = "hf://datasets/asterisk-labs/taco-api-fixtures/data/04-change-detection"
    archive = taco.read(f"{base}/single-zip/dataset.zip", layout="long")
    assert archive.num_rows == 18
    assert (
        archive.column("taco:location")[0]
        .as_py()
        .endswith(",/vsihf/datasets/asterisk-labs/taco-api-fixtures/data/04-change-detection/single-zip/dataset.zip")
    )
    assert taco.read(f"{base}/by-split/.tacocat").num_rows == 6
    folder = taco.read(f"{base}/folder")
    assert folder.num_rows == 6
    assert (
        folder.column("change.rumi")[0]
        .as_py()
        .startswith("/vsihf/datasets/asterisk-labs/taco-api-fixtures/data/04-change-detection/folder/DATA/")
    )

    mirror = "source://asterisk-labs/taco-api-fixtures/data/04-change-detection"
    catalog = taco.read(f"{mirror}/by-split/.tacocat", layout="long")
    assert catalog.num_rows == 18
    location = catalog.column("taco:location")[0].as_py()
    assert ",/vsisource/asterisk-labs/taco-api-fixtures/data/04-change-detection/by-split/" in location
    assert taco.read(f"{mirror}/folder").num_rows == 6
