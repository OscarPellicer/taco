"""Read one sample as typed arrays, using the collection's ``ml:contract``."""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from functools import cached_property
from os import PathLike
from typing import Any

import numpy as np
import pyarrow as pa

from ..metadata.ml import Calibration, MLContract, Slot, SlotKind

CONTRACT_KEY = "ml:contract"
DATA_DIR = "DATA"

#: `prefix*[a,b].ext`, the spec's declaration of a leaf whose file count varies
#: from sample to sample. The bracket is the permitted RANGE of that count, not
#: a character class.
VARIABLE_LEAF = re.compile(r"(?P<stem>.*?)\*\[\d+\s*,\s*\d+\](?P<ext>\.[^.]+)")


@dataclass
class SlotValue:
    """One named piece of a sample, together with what it means.

    A slot is one part of a sample: an image, a mask, a set of boxes, a caption.
    This pairs the decoded array with the slot's declaration, so the numbers can
    be read without going back to the contract -- what they measure, which unit
    they are in, and what the class indices stand for.
    """

    slot: Slot
    array: Any
    sample: int
    counts: list[int] | None = None
    """How many values belong to each object, where the slot declares a
    ``counts_field``. Geometry is stored as one flat run of coordinates, and this
    is what divides it back into objects."""

    @property
    def name(self) -> str:
        return self.slot.name

    @property
    def kind(self) -> SlotKind:
        return self.slot.kind

    @property
    def role(self) -> str | None:
        return self.slot.role

    @property
    def classes(self) -> tuple[str, ...] | None:
        """Class names as a model sees them: descriptions where they exist."""
        names = self.slot.classes
        if names is None:
            return None
        described = self.slot.class_descriptions or []
        return tuple(str(described[i]) if i < len(described) and described[i] else name
                     for i, name in enumerate(names))

    @property
    def physical(self):
        """The array converted to the unit the slot declares, such as reflectance
        or kelvin.

        Raises unless `scale_factor` and `scale_offset` invert the transform the
        values were stored with. They do not when that transform was non-linear
        or computed per image -- a quantile stretch, a gamma curve, an 8-bit
        quicklook -- nor when the stored value is already an index such as NDVI.
        Those slots are `render`, and no multiplication recovers the quantity.
        """
        if self.slot.calibration in (Calibration.RENDER, Calibration.DIGITAL_NUMBER,
                                     Calibration.REQUANTISED, Calibration.UNDECLARED):
            raise ValueError(
                f"{self.name}: calibration is {self.slot.calibration.value!r}, so the "
                f"values do not convert to {self.slot.units or 'a physical unit'}")
        scale = 1.0 if self.slot.scale_factor is None else self.slot.scale_factor
        offset = 0.0 if self.slot.scale_offset is None else self.slot.scale_offset
        return np.asarray(self.array, dtype="float64") * scale + offset

    def __repr__(self) -> str:
        shape = getattr(self.array, "shape", None)
        return (f"<SlotValue {self.name} {self.kind.value}"
                + (f" {tuple(shape)}" if shape else "")
                + (f" [{self.role}]" if self.role else "") + ">")


class Dataset:
    """A TACO collection read as model-ready samples.

    Indexing returns one sample as a mapping of slot name to :class:`SlotValue`,
    with rasters decoded to arrays and metadata columns read alongside them. The
    collection must declare an ``ml:contract``, which is what says how to
    interpret each slot.
    """

    def __init__(self, source: str | PathLike[str]) -> None:
        from ..reader.dataset import Dataset as _Reader

        self.path = str(source)
        self.reader = _Reader(self.path)
        self._zip = zipfile.ZipFile(self.path)
        document = json.loads(self._zip.read("COLLECTION.json"))
        if CONTRACT_KEY not in document:
            raise ValueError(f"{self.path} declares no {CONTRACT_KEY}; "
                             f"taco.ml needs one to type its samples")
        self.collection = document
        self.contract = MLContract.model_validate(document[CONTRACT_KEY])

    @cached_property
    def table(self) -> pa.Table:
        return self.reader.read()

    @cached_property
    def _payloads(self) -> dict[str, tuple[int, int]]:
        """Each payload's path, mapped to its byte range in the archive.

        Covers every metadata level below `sample`, because a sample may nest: a
        group of files is a row with no byte range of its own, and its members
        are described one level further down.
        """
        import pyarrow.parquet as pq

        found: dict[str, tuple[int, int]] = {}
        for name in self._zip.namelist():
            if not (name.startswith("METADATA/") and name.endswith(".parquet")):
                continue
            if name == "METADATA/sample.parquet":
                continue
            table = pq.read_table(io.BytesIO(self._zip.read(name)))
            if "internal:offset" not in table.column_names:
                continue
            paths = table.column("internal:relative_path").to_pylist()
            offsets = table.column("internal:offset").to_pylist()
            sizes = table.column("internal:size").to_pylist()
            found.update({p: (o, s) for p, o, s in zip(paths, offsets, sizes)
                          if o is not None})
        return found

    def __len__(self) -> int:
        return self.table.num_rows

    def __repr__(self) -> str:
        return (f"taco.ml.Dataset({self.collection.get('id')!r}, {len(self)} samples, "
                f"{len(self.contract.inputs)} inputs, {len(self.contract.targets)} targets)")

    def _resolve(self, index: int, pattern: str) -> list[str]:
        """Payload names for one slot of one sample.

        A slot holding a variable number of files is declared `prefix*[a,b].ext`
        (spec 5.2). The `*` is NOT a filesystem glob: it is a cardinal index, so
        the files are `prefix0.ext`, `prefix1.ext`, ... `prefix(k-1).ext` with
        `a <= k <= b` for this sample. Reading it as a glob matches only the
        names whose digits happen to fall in the bracket -- `m*[3,9].tif`
        against `m0..m7` finds one file of eight, and against `m0..m2` none.
        """
        prefix = f"{index}/"
        literal = prefix + pattern
        if literal in self._payloads:
            return [literal]
        match = VARIABLE_LEAF.fullmatch(pattern)
        if match is None:
            return [literal]                      # let `_blob` raise with the name
        stem, extension = match.group("stem"), match.group("ext")
        found, position = [], 0
        while f"{prefix}{stem}{position}{extension}" in self._payloads:
            found.append(f"{prefix}{stem}{position}{extension}")
            position += 1
        return found

    def _blob(self, relative_path: str) -> bytes:
        where = self._payloads.get(relative_path)
        if where is None:
            raise KeyError(f"{relative_path}: no payload in {self.path}")
        offset, size = where
        with open(self.path, "rb") as handle:
            handle.seek(offset)
            return handle.read(size)

    def _raster(self, blob: bytes) -> np.ndarray:
        import rasterio

        with rasterio.MemoryFile(blob) as memory, memory.open() as source:
            return source.read()

    def _value(self, slot: Slot, index: int) -> Any:
        if slot.field:                                   # a metadata column
            column = f"ml:{slot.field}" if f"ml:{slot.field}" in self.table.column_names \
                     else slot.field
            if column not in self.table.column_names:
                return None
            return self.table.column(column)[index].as_py()
        if not slot.path:
            return None
        paths = [slot.path] if isinstance(slot.path, str) else list(slot.path)
        frames = [self._raster(self._blob(name))
                  for pattern in paths
                  for name in self._resolve(index, pattern)]
        if not frames:
            return None
        if slot.kind is SlotKind.MASK_SET:
            # (N, H, W): each member is a single-band file, and the band axis
            # would otherwise sit between the member index and the picture.
            return np.stack([f[0] if f.ndim == 3 and f.shape[0] == 1 else f
                             for f in frames])
        if len(frames) == 1:
            array = frames[0]
            # A mask is (H, W); a raster keeps its band axis.
            return array[0] if slot.kind in (SlotKind.MASK, SlotKind.INSTANCE_ID) else array
        return np.stack(frames)

    def _counts(self, slot: Slot, index: int) -> list[int] | None:
        """The per-object lengths a slot points at, read from the metadata."""
        if not slot.counts_field:
            return None
        for column in (f"ml:{slot.counts_field}", slot.counts_field):
            if column in self.table.column_names:
                values = self.table.column(column)[index].as_py()
                if values is None:
                    return None
                return [int(n) for n in np.atleast_1d(values)]
        return None

    def __getitem__(self, index: int) -> dict[str, SlotValue]:
        if index < 0:
            index += len(self)
        sample: dict[str, SlotValue] = {}
        for slot in list(self.contract.inputs) + list(self.contract.targets):
            try:
                value = self._value(slot, index)
            except KeyError:
                if slot.optional:
                    continue
                raise
            if value is not None:
                sample[slot.name] = SlotValue(slot=slot, array=value, sample=index,
                                              counts=self._counts(slot, index))
        return sample


__all__ = ["Dataset", "SlotValue"]
