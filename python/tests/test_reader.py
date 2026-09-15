from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest

import taco
import taco.reader as reader
import taco.reader.dataset as dataset_module
import taco.reader.engine as engine
import taco.reader.inspect as inspect_module
import taco.reader.native as native
import taco.reader.query as query_module
from taco.errors import ContainerError

from .datasets import get_case


def test_reader_inspects_an_archive(archive: Path) -> None:
    assert taco.reader is reader
    contract = inspect_module.contract(archive)
    assert contract.column("kind").to_pylist() == ["structure"] * 5 + ["level"] * 4
    assert inspect_module.structure(archive) == [
        "before/B02.tif",
        "before/B03.tif",
        "after/B02.tif",
        "mask.tif",
        "extra*[0,3].png",
    ]
    assert inspect_module.levels(archive) == ["sample", "children", "children/after", "children/before"]
    assert inspect_module.derived(archive) == {}
    assert inspect_module.collection(archive)["id"] == "tiny-change"
    assert inspect_module.profile(archive) == "taco"
    assert "read_parquet(" in inspect_module.sql(archive, idx=1)
    with pytest.raises(ValueError, match="layout"):
        inspect_module.sql(archive, layout="flat")


def test_dataset_api(archive: Path) -> None:
    dataset = taco.open_dataset(archive)

    assert isinstance(dataset, taco.Dataset)
    assert dataset.sources == (archive.resolve(),)
    assert dataset.collection.id == "tiny-change"
    assert taco.read(dataset).num_rows == 4
    assert taco.read(archive).num_rows == 4
    assert repr(dataset).startswith("Dataset(")

    long = taco.read(dataset, layout="long", idx=3, files=["mask.tif"])
    assert long.column("path").to_pylist() == ["mask.tif"]
    assert long.column("sample_id").to_pylist() == [3]
    assert long.column("taco:location")[0].as_py().startswith("/vsisubfile/")
    assert "taco:location" not in taco.read(dataset, layout="long", location=False).column_names

    level = taco.read(dataset, level="children/before")
    assert level.num_rows == 8
    assert "internal:current_id" in level.column_names
    assert "taco:location" not in level.column_names


def test_reader_combines_partitions(archive: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy" / "part.zip"
    copy.parent.mkdir()
    shutil.copy(archive, copy)

    dataset = taco.open_dataset([archive, copy])
    assert "sources=2" in repr(dataset)
    assert "2 sources" in dataset._repr_html_()
    wide = taco.read(dataset)
    assert wide.num_rows == 8
    assert set(wide.column("source_file").to_pylist()) == {"dataset.zip", "part.zip"}
    assert taco.read([archive, copy], idx=(2, 4)).num_rows == 4
    assert set(taco.read(dataset, level="sample").column("source_file").to_pylist()) == {"dataset.zip", "part.zip"}


def test_reader_keeps_the_location_of_single_file_samples(tmp_path: Path) -> None:
    case = get_case("single_file")
    path = tmp_path / "single.zip"
    with taco.open_writer(case.collection, path) as writer:
        writer.extend(case.samples)
        writer.run()

    assert all(value.startswith("/vsisubfile/") for value in taco.read(path).column("taco:location").to_pylist())
    assert "taco:location" not in taco.read(path, location=False).column_names


def test_reader_reports_core_errors(archive: Path, tmp_path: Path) -> None:
    with pytest.raises(ContainerError, match="has no level 'nope'"):
        taco.read(archive, level="nope")
    with pytest.raises(ContainerError, match=r"unknown structure leaf: nope\.tif"):
        taco.read(archive, files=["nope.tif"])
    with pytest.raises(ContainerError, match="could not open"):
        taco.read(tmp_path / "missing.zip")
    with pytest.raises(TypeError, match="location"):
        taco.read(archive, location="yes")  # type: ignore[arg-type]


def test_dataset_rejects_unknown_layout(monkeypatch: pytest.MonkeyPatch, collection: taco.Collection) -> None:
    monkeypatch.setattr(dataset_module, "merge_collections", lambda paths: collection)
    dataset = taco.open_dataset("https://example.com/data.zip")

    assert dataset.sources == ("https://example.com/data.zip",)
    with pytest.raises(ValueError, match="must not be empty"):
        taco.open_dataset("")
    with pytest.raises(ValueError, match="at least one"):
        taco.open_dataset([])
    with pytest.raises(ValueError, match="unique"):
        taco.open_dataset(["same.zip", "same.zip"])
    with pytest.raises(ValueError, match="layout"):
        taco.read(dataset, layout="flat")  # type: ignore[arg-type]


def test_dataset_html_escapes_collection_text(monkeypatch: pytest.MonkeyPatch, collection: taco.Collection) -> None:
    dangerous = collection.replace(title="<dataset>", description="<script>alert(1)</script>")
    monkeypatch.setattr(dataset_module, "merge_collections", lambda paths: dangerous)

    html = taco.open_dataset("dataset.zip")._repr_html_()

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;dataset&gt;" in html
    assert "taco.Dataset" in html
    assert "<svg" in html
    assert "Structure" in html
    assert "Metadata" in html
    assert 'class="taco-structure-graph"' in html
    assert '<g class="taco-graph-node taco-graph-folder">' in html
    assert '<g class="taco-graph-node taco-graph-variable">' in html
    assert ">before/<" in html
    assert "extra*[0,3].png" in html
    assert 'role="tooltip"' in html
    assert "Dataset split" in html
    assert "<span>nullable</span><code>false</code>" in html
    assert 'tabindex="0"' not in html
    assert ".taco-field:hover>.taco-field-info" in html


def test_dataset_reads_folder(folder_dataset: Path) -> None:
    dataset = taco.open_dataset(folder_dataset)

    assert dataset.collection.id == "tiny-change"
    html = dataset._repr_html_()
    assert ">FOLDER<" in html
    assert 'aria-label="TACO folder storage"' in html
    assert taco.read(dataset).num_rows == 4
    assert taco.read(dataset, layout="long").num_rows == 19


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (3, "3"), ((1, 4), "[1, 4]")],
)
def test_index_encoding(value, expected) -> None:
    assert query_module.normalize_index(value) == expected


@pytest.mark.parametrize("value", [True, [1], [1, 2, 3], [0, True]])
def test_invalid_indexes(value) -> None:
    with pytest.raises(TypeError, match="idx"):
        query_module.normalize_index(value)


def test_engine_keeps_one_connection_per_thread() -> None:
    engine.close_reader()
    connection = engine.open_reader()
    assert engine.open_reader() is connection
    assert connection.execute("SELECT current_setting('TimeZone')").fetchone() == ("UTC",)

    others: list[object] = []
    thread = threading.Thread(target=lambda: others.append(engine.open_reader()))
    thread.start()
    thread.join()
    assert others[0] is not connection

    engine.close_reader()
    assert engine.open_reader() is not connection


def test_native_reports_a_missing_library(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(native, "_library", None)
    monkeypatch.setenv(native.LIBRARY_ENV, str(tmp_path / "missing-libtaco"))
    with pytest.raises(ContainerError, match="could not load the TACO core"):
        native.profile("dataset.zip")
