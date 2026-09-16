from __future__ import annotations

from types import TracebackType

from tqdm.auto import tqdm


class Progress:
    """Writer progress for interactive terminals."""

    def __init__(self, enabled: bool, total: int, description: str, unit: str = "sample") -> None:
        self._bar: tqdm | None = None
        if enabled:
            self._bar = tqdm(total=total, desc=description, unit=unit, leave=False, dynamic_ncols=True, disable=None)

    def __enter__(self) -> Progress:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._bar is not None:
            self._bar.close()

    def update(self, value: int = 1) -> None:
        if self._bar is not None:
            self._bar.update(value)


__all__ = ["Progress"]
