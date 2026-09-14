from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

import taco
import taco.reader as reader
from taco.errors import ContainerError


def manifest(collection: taco.Collection) -> dict[str, Any]:
    first = collection.to_dict()
    second = collection.replace(dataset_version="2.0.0").to_dict()
    return {
        "taco:container": "versioned",
        "taco:default_version": "2.0.0",
        "taco:versions": {
            "1.0.0": {"href": "1.0.0/", "collection": first},
            "2.0.0": {"href": "2.0.0/", "collection": second},
        },
    }


def write_manifest(root: Path, value: object) -> Path:
    root.mkdir()
    path = root / "taco.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_open_local_root_uses_default_and_embedded_collection(
    monkeypatch: pytest.MonkeyPatch, collection: taco.Collection, tmp_path: Path
) -> None:
    root = tmp_path / "dataset"
    write_manifest(root, manifest(collection))
    monkeypatch.setattr(reader, "_collections", lambda paths: pytest.fail("COLLECTION.json was read"))

    dataset = taco.open_dataset(root)

    assert dataset.sources == ((root / "2.0.0").resolve(),)
    assert dataset.collection.dataset_version == "2.0.0"
    assert dataset.version == "2.0.0"
    assert dataset.versions == ("1.0.0", "2.0.0")
    assert dataset.manifest == (root / "taco.json").resolve()


def test_open_explicit_local_version_is_an_ordinary_dataset(
    monkeypatch: pytest.MonkeyPatch, collection: taco.Collection, tmp_path: Path
) -> None:
    version = tmp_path / "dataset/1.0.0"
    version.mkdir(parents=True)
    monkeypatch.setattr(reader, "_collections", lambda paths: [collection.to_dict()])

    dataset = taco.open_dataset(version)

    assert dataset.sources == (version.resolve(),)
    assert dataset.collection.dataset_version == "1.0.0"
    assert dataset.version == "1.0.0"
    assert dataset.versions == ()
    assert dataset.manifest is None


def test_open_manifest_path_selects_default(collection: taco.Collection, tmp_path: Path) -> None:
    path = write_manifest(tmp_path / "dataset", manifest(collection))

    dataset = taco.open_dataset(path)

    assert dataset.sources == ((path.parent / "2.0.0").resolve(),)
    assert dataset.version == "2.0.0"


class Handler(SimpleHTTPRequestHandler):
    requests: list[str] = []

    def do_GET(self) -> None:
        type(self).requests.append(self.path)
        if self.path == "/unavailable/taco.json":
            self.send_error(503)
            return
        super().do_GET()

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def server(root: Path) -> Iterator[str]:
    Handler.requests = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), lambda *args, **kwargs: Handler(*args, directory=root, **kwargs))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()


@pytest.mark.parametrize("trailing_slash", [False, True])
def test_open_http_root_reads_only_manifest(trailing_slash: bool, collection: taco.Collection, tmp_path: Path) -> None:
    write_manifest(tmp_path / "dataset", manifest(collection))

    with server(tmp_path) as base:
        root = f"{base}/dataset" + ("/" if trailing_slash else "")
        dataset = taco.open_dataset(root)

    assert dataset.sources == (f"{base}/dataset/2.0.0/",)
    assert dataset.collection.dataset_version == "2.0.0"
    assert Handler.requests == ["/dataset/taco.json"]


def test_open_http_root_with_dotted_name_is_discovered(collection: taco.Collection, tmp_path: Path) -> None:
    write_manifest(tmp_path / "dataset.v3", manifest(collection))

    with server(tmp_path) as base:
        dataset = taco.open_dataset(f"{base}/dataset.v3/")

    assert dataset.version == "2.0.0"
    assert Handler.requests == ["/dataset.v3/taco.json"]


def test_open_http_version_url_falls_back_to_direct_dataset(
    monkeypatch: pytest.MonkeyPatch, collection: taco.Collection, tmp_path: Path
) -> None:
    (tmp_path / "dataset/1.0.0").mkdir(parents=True)
    monkeypatch.setattr(reader, "_collections", lambda paths: [collection.to_dict()])

    with server(tmp_path) as base:
        dataset = taco.open_dataset(f"{base}/dataset/1.0.0/")

    assert dataset.sources == (f"{base}/dataset/1.0.0/",)
    assert dataset.version == "1.0.0"
    assert Handler.requests == []


@pytest.mark.parametrize("name", ["part.zip", "PART.ZIP", ".tacocat", ".tacocat/"])
def test_explicit_remote_containers_skip_discovery(
    name: str, monkeypatch: pytest.MonkeyPatch, collection: taco.Collection, tmp_path: Path
) -> None:
    monkeypatch.setattr(reader, "_collections", lambda paths: [collection.to_dict()])

    with server(tmp_path) as base:
        dataset = taco.open_dataset(f"{base}/{name}")

    assert dataset.version == "1.0.0"
    assert Handler.requests == []


def test_read_resolves_versioned_root(
    monkeypatch: pytest.MonkeyPatch, collection: taco.Collection, tmp_path: Path
) -> None:
    root = tmp_path / "dataset"
    write_manifest(root, manifest(collection))
    captured: list[object] = []

    def fake_read(source, **options):
        captured.append((source, options))
        return pa.table({"value": [1]})

    monkeypatch.setattr(reader, "read", fake_read)

    result = taco.read(root, idx=3)

    assert result.num_rows == 1
    assert captured[0][0] == ((root / "2.0.0").resolve(),)


def test_absolute_href_is_preserved(collection: taco.Collection, tmp_path: Path) -> None:
    value = manifest(collection)
    value["taco:versions"]["2.0.0"]["href"] = "https://cdn.example/dataset.zip"
    path = write_manifest(tmp_path / "dataset", value)

    dataset = taco.open_dataset(path)

    assert dataset.sources == ("https://cdn.example/dataset.zip",)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.update({"taco:container": "zip"}), "taco:container"),
        (lambda value: value.update({"taco:versions": {}}), "at least one"),
        (lambda value: value.update({"taco:versions": []}), "must be an object"),
        (lambda value: value.pop("taco:default_version"), "taco:default_version"),
        (lambda value: value.update({"taco:default_version": "3.0.0"}), "not present"),
        (
            lambda value: value["taco:versions"].update({"latest": value["taco:versions"].pop("1.0.0")}),
            "must follow Semantic Versioning",
        ),
        (lambda value: value["taco:versions"]["2.0.0"].update({"href": ""}), "non-empty href"),
        (
            lambda value: value["taco:versions"]["1.0.0"].update({"href": ""}),
            "version '1.0.0' needs a non-empty href",
        ),
        (
            lambda value: value["taco:versions"]["2.0.0"]["collection"].update({"dataset_version": "1.0.0"}),
            "embeds collection dataset_version",
        ),
        (
            lambda value: value["taco:versions"]["2.0.0"].update({"collection": {"dataset_version": "2.0.0"}}),
            "embeds an invalid collection",
        ),
    ],
)
def test_invalid_manifest_is_rejected(
    change: Callable[[dict[str, Any]], object], message: str, collection: taco.Collection, tmp_path: Path
) -> None:
    value = manifest(collection)
    change(value)
    path = write_manifest(tmp_path / "dataset", value)

    with pytest.raises(ContainerError, match=message):
        taco.open_dataset(path)


def test_invalid_json_and_missing_explicit_manifest_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    root.mkdir()
    path = root / "taco.json"
    path.write_text("not JSON", encoding="utf-8")
    with pytest.raises(ContainerError, match="not valid JSON"):
        taco.open_dataset(path)

    path.unlink()
    with pytest.raises(ContainerError, match="does not exist"):
        taco.open_dataset(path)


def test_http_errors_other_than_not_found_do_not_fall_back(tmp_path: Path) -> None:
    with server(tmp_path) as base, pytest.raises(ContainerError, match="HTTP 503"):
        taco.open_dataset(f"{base}/unavailable/")
