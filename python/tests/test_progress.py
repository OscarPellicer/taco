from __future__ import annotations

import pytest

import taco
from taco.writer import progress


class _Bar:
    def __init__(self, options: dict[str, object]) -> None:
        self.options = options
        self.updates = 0
        self.closed = False

    def update(self, value: int = 1) -> None:
        self.updates += value

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("name", "options", "samples", "descriptions", "updates"),
    [
        ("data.zip", {}, 1, ["planning data.zip", "metadata data.zip", "packing data.zip"], [1, 1, 1]),
        ("data", {}, 1, ["writing data"], [1]),
        (
            "parts.zip",
            {"partition_size": 1, "workers": 2},
            2,
            ["building parts.zip"],
            [2],
        ),
    ],
)
def test_writer_progress(
    name, options, samples, descriptions, updates, tmp_path, collection, make_sample, monkeypatch
) -> None:
    bars: list[_Bar] = []

    def tqdm(**options: object) -> _Bar:
        bar = _Bar(options)
        bars.append(bar)
        return bar

    monkeypatch.setattr(progress, "tqdm", tqdm)
    with taco.open_writer(collection, tmp_path / name, progress=True, **options) as writer:
        writer.extend(make_sample(index) for index in range(samples))
        writer.run()

    assert [bar.options["desc"] for bar in bars] == descriptions
    assert [bar.updates for bar in bars] == updates
    assert all(bar.closed for bar in bars)


def test_progress_hides_outside_a_terminal(monkeypatch) -> None:
    seen: list[dict[str, object]] = []

    def tqdm(**options: object) -> _Bar:
        seen.append(options)
        return _Bar(options)

    monkeypatch.setattr(progress, "tqdm", tqdm)
    with progress.Progress(True, 1, "writing") as bar:
        bar.update()
    # disable=None leaves the decision to tqdm, which checks stderr.
    assert seen[0]["disable"] is None

    seen.clear()
    with progress.Progress(False, 1, "writing") as bar:
        bar.update()
    assert seen == []
