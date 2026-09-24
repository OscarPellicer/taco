"""What `taco.ml.Dataset` makes of each kind of slot, on small real archives."""

from __future__ import annotations

import io
import struct
import wave
from pathlib import Path

import numpy as np
import pytest
from pydantic import BaseModel

import taco
from taco.metadata.ml import SlotKind, Task
from taco.ml import Dataset
from taco.ml.dataset import _wave

rasterio = pytest.importorskip("rasterio")


def _tif(path: Path, array: np.ndarray, *, nodata: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    bands, height, width = array.shape
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=bands,
                       dtype=array.dtype, nodata=nodata, crs="EPSG:4326",
                       transform=rasterio.transform.from_origin(0, height, 1, 1)) as sink:
        sink.write(array)
    return path


def _archive(path: Path, structure: list[str], contract: dict, samples: list[taco.Sample],
             *levels: taco.Level) -> Path:
    collection = taco.Collection(
        contract=taco.Contract(structure=structure, metadata=taco.MetadataSchema(*levels)),
        id="reading", dataset_version="1.0.0", description="Fixture for taco.ml reading",
        licenses=["CC-BY-4.0"], providers=[{"name": "Asterisk Labs", "roles": ["producer"]}],
        metadata=taco.CollectionMetadata.from_flat({"ml:contract": contract}),
    )
    with taco.open_writer(collection, path) as writer:
        writer.extend(samples)
        writer.run()
    return path


class Boxes(BaseModel):
    boxes: list[float]
    per_query: list[int]


class Frames(BaseModel):
    frames: int


class Date(BaseModel):
    date: str


def test_names_print_as_they_are_stored() -> None:
    assert str(Task.COUNTING) == f"{Task.COUNTING}" == "counting"
    assert f"{SlotKind.MASK:>6}" == "  mask"


def test_boxes_come_back_one_per_row_and_their_counts_must_add_up(tmp_path: Path) -> None:
    image = _tif(tmp_path / "src" / "image.tif", np.zeros((1, 4, 4), "uint8"))
    contract = {"inputs": [{"name": "image", "kind": "raster", "path": "image.tif"}],
                "targets": [{"name": "boxes", "kind": "bbox_2d", "field": "boxes",
                             "counts_field": "per_query"}]}

    def build(name: str, counts: list[int]) -> Dataset:
        sample = taco.Sample(metadata=taco.Metadata(ml=Boxes(boxes=[0, 0, 1, 1, 2, 2, 3, 3],
                                                             per_query=counts)),
                             assets=[taco.Asset(image, path="image.tif")])
        return Dataset(_archive(tmp_path / name, ["image.tif"], contract, [sample],
                                taco.Level("sample", ml=Boxes)))

    value = build("good.zip", [1, 1])[0]["boxes"]
    assert value.array.shape == (2, 4)
    assert value.counts == [1, 1]
    with pytest.raises(ValueError, match="adds up to 3"):
        build("bad.zip", [1, 2])[0]


def test_masked_hides_nodata_and_ignored_labels(tmp_path: Path) -> None:
    image = _tif(tmp_path / "src" / "image.tif", np.array([[[0, 5], [6, 7]]], "uint16"))
    label = _tif(tmp_path / "src" / "label.tif", np.array([[[1, 255], [0, 1]]], "uint8"))
    contract = {"inputs": [{"name": "image", "kind": "raster", "path": "image.tif", "nodata": 0}],
                "targets": [{"name": "label", "kind": "mask", "path": "label.tif",
                             "classes": ["a", "b"], "ignore_index": 255}]}
    sample = taco.Sample(assets=[taco.Asset(image, path="image.tif"),
                                 taco.Asset(label, path="label.tif")])
    path = _archive(tmp_path / "x.zip", ["image.tif", "label.tif"], contract, [sample],
                    taco.Level("sample"))
    masked = Dataset(path, masked=True)[0]
    assert masked["image"].valid.tolist() == [[[False, True], [True, True]]]
    assert masked["label"].valid.tolist() == [[True, False], [True, True]]
    assert not np.ma.isMaskedArray(Dataset(path)[0]["image"].array)


def test_a_series_stacked_in_one_file_is_cut_by_its_frame_count(tmp_path: Path) -> None:
    stack = np.arange(6 * 2 * 2, dtype="uint8").reshape(6, 2, 2)      # 3 frames x 2 bands
    series = _tif(tmp_path / "src" / "series.tif", stack)
    contract = {"inputs": [{"name": "series", "kind": "raster_series", "path": "series.tif",
                            "frames_field": "frames",
                            "bands": [{"index": 0}, {"index": 1}]}]}
    sample = taco.Sample(metadata=taco.Metadata(ml=Frames(frames=3)),
                         assets=[taco.Asset(series, path="series.tif")])
    path = _archive(tmp_path / "x.zip", ["series.tif"], contract, [sample],
                    taco.Level("sample", ml=Frames))
    array = Dataset(path)[0]["series"].array
    assert array.shape == (3, 2, 2, 2)
    assert array[2, 1].tolist() == stack[5].tolist()


def test_per_frame_dates_follow_the_frame_numbers(tmp_path: Path) -> None:
    # Twelve frames, so the stored rows (t0, t1, t10, t11, t2, ...) and the frame
    # numbers disagree about the order.
    frames = [taco.Asset(_tif(tmp_path / "src" / f"t{i}.tif", np.full((1, 2, 2), i, "uint8")),
                         path=f"s2/t{i}.tif", metadata=taco.Metadata(ml=Date(date=f"2020-{i + 1:02d}-01")))
              for i in range(12)]
    contract = {"inputs": [{"name": "s2", "kind": "raster_series", "path": "s2/t*[1,12].tif",
                            "structure": "series", "time_field": "children/s2:date"}]}
    sample = taco.Sample(assets=frames)
    path = _archive(tmp_path / "x.zip", ["s2/t*[1,12].tif"], contract, [sample],
                    taco.Level("sample"), taco.Level("children/s2", ml=Date))
    value = Dataset(path)[0]["s2"]
    assert [int(frame[0, 0, 0]) for frame in value.array] == list(range(12))
    assert value.times == [f"2020-{i + 1:02d}-01" for i in range(12)]


def test_a_reference_names_a_level_only_when_it_is_one(tmp_path: Path) -> None:
    image = _tif(tmp_path / "src" / "image.tif", np.zeros((1, 2, 2), "uint8"))
    contract = {"inputs": [{"name": "image", "kind": "raster", "path": "image.tif"}],
                "targets": [{"name": "frames", "kind": "scalar", "field": "sample:frames"}]}
    sample = taco.Sample(metadata=taco.Metadata(ml=Frames(frames=7)),
                         assets=[taco.Asset(image, path="image.tif")])
    dataset = Dataset(_archive(tmp_path / "x.zip", ["image.tif"], contract, [sample],
                               taco.Level("sample", ml=Frames)))
    assert dataset[0]["frames"].array == 7
    # `ml:frames` is a column name with a namespace, not a level called `ml`.
    assert dataset.lookup(0, "ml:frames") == dataset.lookup(0, "frames") == 7
    assert dataset.column("frames").to_pylist() == [7]


def test_read_decodes_only_the_slots_asked_for(tmp_path: Path) -> None:
    image = _tif(tmp_path / "src" / "image.tif", np.zeros((1, 2, 2), "uint8"))
    contract = {"inputs": [{"name": "image", "kind": "raster", "path": "image.tif"}],
                "targets": [{"name": "frames", "kind": "scalar", "field": "frames"}]}
    sample = taco.Sample(metadata=taco.Metadata(ml=Frames(frames=7)),
                         assets=[taco.Asset(image, path="image.tif")])
    dataset = Dataset(_archive(tmp_path / "x.zip", ["image.tif"], contract, [sample],
                               taco.Level("sample", ml=Frames)))
    assert set(dataset.read(0, ["frames"])) == {"frames"}
    with pytest.raises(KeyError, match="no slot"):
        dataset.read(0, ["nothing"])


def test_wave_files_decode_to_channels_and_a_sample_rate() -> None:
    samples = np.array([[0, 16384], [-16384, 32767]], dtype="<i2")     # 2 frames x 2 channels
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sink:
        sink.setnchannels(2)
        sink.setsampwidth(2)
        sink.setframerate(8000)
        sink.writeframes(samples.tobytes())
    array, rate = _wave(buffer.getvalue(), "clip.wav")
    assert rate == 8000
    assert array.shape == (2, 2)
    assert array[0].tolist() == pytest.approx([0.0, -0.5])
    assert struct.unpack("<4s", buffer.getvalue()[:4])[0] == b"RIFF"


def test_a_large_raster_is_read_smaller_only_when_nothing_depends_on_its_size(tmp_path: Path) -> None:
    image = _tif(tmp_path / "src" / "image.tif", np.arange(64, dtype="uint8").reshape(1, 8, 8))
    alone = {"inputs": [{"name": "image", "kind": "raster", "path": "image.tif"}]}
    sample = taco.Sample(assets=[taco.Asset(image, path="image.tif")])
    path = _archive(tmp_path / "x.zip", ["image.tif"], alone, [sample], taco.Level("sample"))
    assert Dataset(path)[0]["image"].array.shape == (1, 8, 8)
    assert Dataset(path, max_pixels=16)[0]["image"].array.shape == (1, 4, 4)

    boxed = dict(alone, targets=[{"name": "boxes", "kind": "bbox_2d", "field": "boxes"}])
    with_boxes = taco.Sample(metadata=taco.Metadata(ml=Boxes(boxes=[0, 0, 8, 8], per_query=[1])),
                             assets=[taco.Asset(image, path="image.tif")])
    path = _archive(tmp_path / "y.zip", ["image.tif"], boxed, [with_boxes],
                    taco.Level("sample", ml=Boxes))
    # The boxes are in the full-size picture's pixels, so it stays full size.
    assert Dataset(path, max_pixels=16)[0]["image"].array.shape == (1, 8, 8)
