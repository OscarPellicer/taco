from __future__ import annotations

import json
from pathlib import Path

from taco.reader.manifest import join_manifest_href, manifest_candidate, resolve_dataset


def cases() -> dict[str, list[dict[str, str | None]]]:
    path = Path(__file__).parent / "data" / "reader-resolution.json"
    if not path.is_file():
        path = Path(__file__).parents[2] / "r" / "inst" / "conformance" / "reader-resolution.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_candidate_conformance() -> None:
    for case in cases()["manifest_candidates"]:
        assert manifest_candidate(case["source"]) == case["expected"]


def test_manifest_href_conformance() -> None:
    for case in cases()["manifest_hrefs"]:
        assert case["href"] is not None
        assert join_manifest_href(case["candidate"], case["href"]) == case["expected"]


def test_file_uri_without_manifest_is_direct(tmp_path: Path) -> None:
    uri = tmp_path.as_uri()
    resolution = resolve_dataset(uri)
    assert resolution.sources == (uri,)
    assert resolution.manifest is None
