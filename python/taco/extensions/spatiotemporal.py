from __future__ import annotations

import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

import pyarrow as pa

from ..metadata._base import Extension, ExtensionContext
from ..metadata.spatiotemporal import ISTAC as ISTACMetadata
from ..metadata.spatiotemporal import STAC as STACMetadata


def _point_wkb(longitude: float, latitude: float) -> bytes:
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise ValueError("centroid coordinates must be finite")
    if not -180 <= longitude <= 180:
        raise ValueError(f"centroid longitude {longitude} is outside [-180, 180]")
    if not -90 <= latitude <= 90:
        raise ValueError(f"centroid latitude {latitude} is outside [-90, 90]")
    return struct.pack("<BIdd", 1, 1, longitude, latitude)


def _wgs84(crs: str, x: float, y: float) -> tuple[float, float]:
    normalized = crs.strip().upper().replace(" ", "")
    if normalized in {"EPSG:4326", "OGC:CRS84", "CRS84"}:
        return x, y
    try:
        from pyproj import CRS, Transformer
        from pyproj.exceptions import CRSError
    except ImportError as exc:
        raise ImportError("projected STAC/ISTAC metadata requires 'pyproj'") from exc
    try:
        source = CRS.from_user_input(crs)
    except CRSError as exc:
        raise ValueError(f"invalid CRS: {crs}") from exc
    longitude, latitude = Transformer.from_crs(source, CRS.from_epsg(4326), always_xy=True).transform(x, y)
    return float(longitude), float(latitude)


def raster_centroid(crs: str, geotransform: Sequence[float], tensor_shape: Sequence[int]) -> bytes:
    """Return the affine-grid center as an EPSG:4326 WKB point."""
    if len(tensor_shape) < 2:
        raise ValueError("stac:tensor_shape must have at least two dimensions")
    if len(geotransform) != 6:
        raise ValueError("stac:geotransform must contain six values")
    rows, columns = int(tensor_shape[-2]), int(tensor_shape[-1])
    origin_x, pixel_width, row_rotation, origin_y, column_rotation, pixel_height = map(float, geotransform)
    center_column = columns / 2
    center_row = rows / 2
    x = origin_x + center_column * pixel_width + center_row * row_rotation
    y = origin_y + center_column * column_rotation + center_row * pixel_height
    longitude, latitude = _wgs84(crs, x, y)
    return _point_wkb(longitude, latitude)


def geometry_centroid(crs: str, geometry: bytes, *, check_antimeridian: bool) -> bytes:
    """Return an irregular geometry's center as an EPSG:4326 WKB point."""
    try:
        from shapely.wkb import loads as load_wkb  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError("automatic ISTAC centroids require 'shapely'") from exc
    try:
        shape = load_wkb(geometry)
    except Exception as exc:
        raise ValueError("istac:geometry is not valid WKB") from exc
    if shape.is_empty:
        raise ValueError("istac:geometry is empty")

    try:
        from pyproj import CRS
        from pyproj.exceptions import CRSError
    except ImportError as exc:
        raise ImportError("automatic ISTAC centroids require 'pyproj'") from exc
    try:
        source = CRS.from_user_input(crs)
    except CRSError as exc:
        raise ValueError(f"invalid CRS: {crs}") from exc

    if source.is_geographic and check_antimeridian:
        try:
            import antimeridian
        except ImportError as exc:
            raise ImportError("ISTAC(check_antimeridian=True) requires 'taco-eo[antimeridian]'") from exc
        fixed = antimeridian.fix_shape(shape, fix_winding=True)
        center = antimeridian.centroid(fixed)
    else:
        center = shape.centroid
    longitude, latitude = _wgs84(crs, float(center.x), float(center.y))
    return _point_wkb(longitude, latitude)


def _middle(start: datetime, end: datetime | None, current: datetime | None) -> datetime | None:
    return current if current is not None or end is None else start + (end - start) / 2


def _column(context: ExtensionContext, name: str) -> Sequence[Any]:
    try:
        return context.columns[name]
    except KeyError as exc:
        raise ValueError(f"extension input {name!r} is unavailable") from exc


@dataclass(frozen=True)
class STAC(Extension):
    """Complete regular spatiotemporal metadata during ``writer.run()``."""

    __taco_scopes__: ClassVar[frozenset[str]] = frozenset({"sample", "folder"})
    model: type[STACMetadata] = STACMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.model, type) or not issubclass(self.model, STACMetadata):
            raise TypeError("STAC model must inherit taco.metadata.sample.STAC")

    @property
    def input_model(self) -> type[STACMetadata]:
        return self.model

    @property
    def requires(self) -> tuple[str, ...]:
        return ("stac:crs", "stac:tensor_shape", "stac:geotransform", "stac:time_start", "stac:time_end")

    @property
    def fields(self) -> pa.Schema:
        return pa.schema(
            [
                pa.field(
                    "centroid", pa.binary(), nullable=False, metadata={b"description": b"Centroid in EPSG:4326 as WKB"}
                ),
                pa.field(
                    "time_middle",
                    pa.timestamp("us", tz="UTC"),
                    nullable=True,
                    metadata={b"description": b"Acquisition midpoint"},
                ),
            ]
        )

    def run(self, context: ExtensionContext) -> Mapping[str, Sequence[Any]]:
        centroids = []
        middles = []
        for crs, shape, transform, start, end, centroid, middle in zip(
            _column(context, "stac:crs"),
            _column(context, "stac:tensor_shape"),
            _column(context, "stac:geotransform"),
            _column(context, "stac:time_start"),
            _column(context, "stac:time_end"),
            _column(context, "stac:centroid"),
            _column(context, "stac:time_middle"),
            strict=True,
        ):
            centroids.append(centroid if centroid is not None else raster_centroid(crs, transform, shape))
            middles.append(_middle(start, end, middle))
        return {"centroid": centroids, "time_middle": middles}


@dataclass(frozen=True)
class ISTAC(Extension):
    """Complete irregular spatiotemporal metadata during ``writer.run()``."""

    check_antimeridian: bool = False
    model: type[ISTACMetadata] = ISTACMetadata

    __taco_scopes__: ClassVar[frozenset[str]] = frozenset({"sample", "folder"})

    def __post_init__(self) -> None:
        if not isinstance(self.model, type) or not issubclass(self.model, ISTACMetadata):
            raise TypeError("ISTAC model must inherit taco.metadata.sample.ISTAC")

    @property
    def input_model(self) -> type[ISTACMetadata]:
        return self.model

    @property
    def requires(self) -> tuple[str, ...]:
        return ("istac:crs", "istac:geometry", "istac:time_start", "istac:time_end")

    @property
    def fields(self) -> pa.Schema:
        return pa.schema(
            [
                pa.field(
                    "centroid", pa.binary(), nullable=False, metadata={b"description": b"Centroid in EPSG:4326 as WKB"}
                ),
                pa.field(
                    "time_middle",
                    pa.timestamp("us", tz="UTC"),
                    nullable=True,
                    metadata={b"description": b"Acquisition midpoint"},
                ),
            ]
        )

    def configuration(self) -> Mapping[str, Any]:
        return {"check_antimeridian": self.check_antimeridian}

    def run(self, context: ExtensionContext) -> Mapping[str, Sequence[Any]]:
        centroids = []
        middles = []
        for crs, geometry, start, end, centroid, middle in zip(
            _column(context, "istac:crs"),
            _column(context, "istac:geometry"),
            _column(context, "istac:time_start"),
            _column(context, "istac:time_end"),
            _column(context, "istac:centroid"),
            _column(context, "istac:time_middle"),
            strict=True,
        ):
            centroids.append(
                centroid
                if centroid is not None
                else geometry_centroid(crs, geometry, check_antimeridian=self.check_antimeridian)
            )
            middles.append(_middle(start, end, middle))
        return {"centroid": centroids, "time_middle": middles}


__all__ = ["ISTAC", "STAC", "geometry_centroid", "raster_centroid"]
