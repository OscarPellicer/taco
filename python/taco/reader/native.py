"""The native TACO core, shared with the R and Julia packages."""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Sequence
from os import PathLike, fspath
from pathlib import Path
from typing import Any

from cffi import FFI

from ..errors import ContainerError

API_VERSION = 1
LIBRARY_ENV = "TACO_LIB"

_ffi = FFI()
_ffi.cdef(
    """
    typedef enum {
        TACO_OK = 0,
        TACO_ERR_INVALID = 1,
        TACO_ERR_IO = 2,
        TACO_ERR_NOT_FOUND = 3,
        TACO_ERR_INTERNAL = 99
    } taco_status;

    int taco_api_version(void);
    const char* taco_version_string(void);
    const char* taco_last_error(void);
    void taco_free(char* text);

    typedef struct taco_dataset taco_dataset;
    taco_status taco_open(const char* source, const char* cache_dir, taco_dataset** out);
    void taco_close(taco_dataset* dataset);
    const char* taco_dataset_source(const taco_dataset* dataset);
    const char* taco_dataset_container(const taco_dataset* dataset);
    const char* taco_dataset_collection(const taco_dataset* dataset);
    size_t taco_dataset_level_count(const taco_dataset* dataset);
    const char* taco_dataset_level(const taco_dataset* dataset, size_t index);
    size_t taco_dataset_structure_count(const taco_dataset* dataset);
    const char* taco_dataset_structure(const taco_dataset* dataset, size_t index);
    const char* taco_dataset_derived(const taco_dataset* dataset);

    typedef struct {
        const char* idx;
        const char* level;
        int pivoted;
        const char* const* files;
        size_t file_count;
        int location;
    } taco_read_options;

    taco_status taco_sql(const taco_dataset* const* datasets, size_t count,
                         const taco_read_options* options, char** out_sql);
    taco_status taco_profile(const char* source, char** out_name);
    taco_status taco_manifest_candidate(const char* source, char** out_candidate);
    taco_status taco_join_manifest_href(const char* candidate, const char* href, char** out_source);
    taco_status taco_resolve(const char* source, char** out_json);
    """
)

_lock = threading.Lock()
_library: Any = None


def _library_path() -> str:
    configured = os.environ.get(LIBRARY_ENV)
    if configured:
        return configured
    name = {"darwin": "libtaco.dylib", "win32": "taco.dll"}.get(sys.platform, "libtaco.so")
    return str(Path(__file__).resolve().parents[1] / "_lib" / name)


def _load() -> Any:
    global _library
    if _library is None:
        with _lock:
            if _library is None:
                path = _library_path()
                try:
                    library = _ffi.dlopen(path)
                except OSError as exc:
                    raise ContainerError(
                        f"could not load the TACO core from {path}: {exc}. "
                        f"Build it with `make core` or set {LIBRARY_ENV}."
                    ) from exc
                if library.taco_api_version() != API_VERSION:
                    raise ContainerError(
                        f"the TACO core at {path} has C API {library.taco_api_version()}, expected {API_VERSION}"
                    )
                _library = library
    return _library


def _encode(value: str | PathLike[str]) -> bytes:
    return fspath(value).encode("utf-8")


def _check(status: int) -> None:
    if status != 0:
        raise ContainerError(_ffi.string(_load().taco_last_error()).decode("utf-8", errors="replace"))


def _text(pointer: Any) -> str | None:
    return None if pointer == _ffi.NULL else str(_ffi.string(pointer).decode("utf-8"))


def _take(pointer: Any) -> str | None:
    try:
        return _text(pointer)
    finally:
        if pointer != _ffi.NULL:
            _load().taco_free(pointer)


def _call(function: str, *arguments: Any) -> str | None:
    out = _ffi.new("char **")
    _check(getattr(_load(), function)(*arguments, out))
    return _take(out[0])


class NativeDataset:
    """An open dataset whose metadata is available locally."""

    __slots__ = ("_handle",)

    def __init__(self, source: str | PathLike[str]) -> None:
        library = _load()
        out = _ffi.new("taco_dataset **")
        _check(library.taco_open(_encode(source), _ffi.NULL, out))
        self._handle = _ffi.gc(out[0], library.taco_close)

    @property
    def source(self) -> str:
        return str(_text(_load().taco_dataset_source(self._handle)))

    @property
    def container(self) -> str:
        return str(_text(_load().taco_dataset_container(self._handle)))

    @property
    def collection(self) -> str:
        return str(_text(_load().taco_dataset_collection(self._handle)))

    @property
    def levels(self) -> list[str]:
        library = _load()
        return [
            str(_text(library.taco_dataset_level(self._handle, index)))
            for index in range(library.taco_dataset_level_count(self._handle))
        ]

    @property
    def structure(self) -> list[str]:
        library = _load()
        return [
            str(_text(library.taco_dataset_structure(self._handle, index)))
            for index in range(library.taco_dataset_structure_count(self._handle))
        ]

    @property
    def derived(self) -> str | None:
        return _text(_load().taco_dataset_derived(self._handle))


def sql(
    datasets: Sequence[NativeDataset],
    *,
    idx: str | None,
    level: str | None,
    pivoted: bool,
    files: Sequence[str] | None,
    location: bool,
) -> str:
    """The query that reads the datasets, as one union when there are several."""
    # cffi owns every buffer below until the call returns.
    keep: list[Any] = []

    def text(value: str | None) -> Any:
        if value is None:
            return _ffi.NULL
        keep.append(_ffi.new("char[]", value.encode("utf-8")))
        return keep[-1]

    options = _ffi.new("taco_read_options *")
    options.idx = text(idx)
    options.level = text(level)
    options.pivoted = int(pivoted)
    options.location = int(location)
    if files is not None:
        array = _ffi.new("char *[]", [text(name) for name in files])
        keep.append(array)
        options.files = array
        options.file_count = len(files)
    handles = _ffi.new("taco_dataset *[]", [dataset._handle for dataset in datasets])
    return str(_call("taco_sql", handles, len(datasets), options))


def profile(source: str | PathLike[str]) -> str:
    return str(_call("taco_profile", _encode(source)))


def manifest_candidate(source: str | PathLike[str]) -> str | None:
    return _call("taco_manifest_candidate", _encode(source))


def join_manifest_href(candidate: str | PathLike[str], href: str) -> str:
    return str(_call("taco_join_manifest_href", _encode(candidate), href.encode("utf-8")))


def resolve(source: str | PathLike[str]) -> dict[str, Any]:
    value = json.loads(str(_call("taco_resolve", _encode(source))))
    assert isinstance(value, dict)
    return value


__all__ = [
    "LIBRARY_ENV",
    "NativeDataset",
    "join_manifest_href",
    "manifest_candidate",
    "profile",
    "resolve",
    "sql",
]
