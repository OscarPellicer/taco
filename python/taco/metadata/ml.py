"""Machine-learning contract: which assets a model reads, and what it predicts.

``taco:structure`` says how a dataset is stored. This says how it is used: the
role of each asset, the shape of each target, and the physical meaning of the
values.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from ._base import CollectionModel, ScopedModel


class SlotKind(str, Enum):
    """What a slot holds, and therefore how it is read or predicted."""

    RASTER = "raster"                    #: (C, H, W), e.g. a 3x512x512 RGB tile
    RASTER_SERIES = "raster_series"      #: (T, C, H, W), e.g. 12 monthly Sentinel-2 scenes
    MASK = "mask"                        #: (H, W) class indices, e.g. 0..10 land cover
    MASK_SERIES = "mask_series"          #: (T, H, W) class indices, one per date
    MASK_SET = "mask_set"                #: (N, H, W) binary masks, one per object
    INSTANCE_ID = "instance_id"          #: (H, W) object ids, e.g. 499 field parcels
    SCALAR = "scalar"                    #: one number, e.g. 12.4 (canopy height, m)
    CLASS_INDEX = "class_index"          #: one index, e.g. 3 -> "farmland"
    CLASS_MULTIHOT = "class_multihot"    #: (K,) of 0/1, e.g. 4 of 19 land-cover labels
    CLASS_SEQUENCE = "class_sequence"    #: (N,) indices, one per object or question
    BBOX_2D = "bbox_2d"                  #: (N, 4) x0, y0, x1, y1 in pixels
    BBOX_OBB = "bbox_obb"                #: (N, 5) cx, cy, w, h, angle; angle in radians
    POLYGON = "polygon"                  #: flat (x, y) pixel vertices plus a per-ring length
    POINT_2D = "point_2d"                #: (N, 2) x, y in pixels
    TEXT = "text"                        #: one string, e.g. a caption
    TEXT_SEQUENCE = "text_sequence"      #: (N,) strings, e.g. questions and answers
    AUDIO = "audio"                      #: (channels, samples), e.g. 1 x 220500 at 44.1 kHz
    VIDEO = "video"                      #: an encoded clip, read frame by frame
    VECTOR = "vector"                    #: (D,) embedding, e.g. 768 floats
    GRAPH = "graph"                      #: nodes and edges


class Modality(str, Enum):
    """What the values are a measurement of."""

    OPTICAL = "optical"                  #: RGB or RGB-NIR, e.g. aerial or PlanetScope
    MULTISPECTRAL = "multispectral"      #: a few to tens of bands, e.g. Sentinel-2
    HYPERSPECTRAL = "hyperspectral"      #: hundreds of contiguous bands, e.g. EnMAP
    SAR = "sar"                          #: radar backscatter, e.g. Sentinel-1 VV/VH
    THERMAL = "thermal"                  #: emitted radiance, e.g. Landsat ST_B10
    ELEVATION = "elevation"              #: terrain or surface height, e.g. a DEM
    ATMOSPHERIC = "atmospheric"          #: column or profile, e.g. Sentinel-5P NO2
    BIOPHYSICAL = "biophysical"          #: a modelled quantity, e.g. biomass, yield
    LABEL_RASTER = "label_raster"        #: annotation, not a measurement
    MAP_RENDER = "map_render"            #: a rendered map or basemap tile
    TEXT = "text"
    AUDIO = "audio"
    VIDEO = "video"
    VECTOR = "vector"
    OTHER = "other"


class Calibration(str, Enum):
    """Whether the stored values convert back to a physical quantity."""

    PHYSICAL = "physical"                #: already in `units`, e.g. 284.3 K
    SCALED = "scaled"                    #: `value * scale_factor + scale_offset` gives `units`
    DIGITAL_NUMBER = "digital_number"    #: a real quantity, but no conversion published here
    REQUANTISED = "requantised"          #: rescaled to fit a storage type, original range lost
    RENDER = "render"                    #: an 8-bit picture of the data, e.g. a SAR quicklook
    UNDECLARED = "undeclared"            #: the publisher does not say


class ProcessingLevel(str, Enum):
    """How far the values have been processed from raw sensor output."""

    TOA = "toa"                          #: top of atmosphere, e.g. Sentinel-2 L1C
    BOA = "boa"                          #: bottom of atmosphere, e.g. Sentinel-2 L2A
    DERIVED = "derived"                  #: computed from another product, e.g. an index
    NA = "n/a"                           #: not applicable, e.g. an annotation raster
    UNKNOWN = "unknown"                  #: not stated


class Band(ScopedModel):
    """One band of a slot. Spectral and radar fields are both optional, so one
    band table serves every modality."""

    index: int
    common_name: str | None = None
    center_wavelength: float | None = Field(default=None, description="Centre wavelength, in nm")
    full_width_half_max: float | None = Field(
        default=None, description="Full width at half maximum, in nm")
    variable: str | None = Field(
        default=None, description="Measured quantity, preferably a CF standard name")
    polarisation: Literal["VV", "VH", "HH", "HV", "VV-VH", "HH-HV"] | None = Field(
        default=None, description="Radar transmit and receive polarisation")
    unit: str | None = None
    gsd_m: float | None = Field(default=None, description="Ground sample distance, in metres")
    nodata: float | None = None


class Slot(ScopedModel):
    """One thing a model reads or predicts."""

    name: str
    kind: SlotKind
    role: Literal["input", "target"] | None = Field(
        default=None, description="Set from the list the slot appears in")
    modality: Modality | None = None
    structure: Literal["single", "bitemporal", "series", "video", "mosaic", "cross-view"] = "single"

    path: str | list[str] | None = Field(
        default=None,
        description="Asset path within the sample; a list for a series, in temporal order")
    field: str | None = Field(default=None, description="Metadata column holding the value")

    bands: list[Band] = Field(default_factory=list)
    calibration: Calibration | None = None
    scale_factor: float | None = Field(
        default=None, description="Multiplicative factor used to unpack values")
    scale_offset: float | None = Field(
        default=None, description="Offset used to unpack values")
    approx_scale_factor: float | None = Field(
        default=None,
        description="Approximate multiplicative factor, where no exact conversion is published")
    approx_scale_offset: float | None = Field(
        default=None, description="Offset paired with `approx_scale_factor`")
    processing_level: ProcessingLevel | None = None
    units: str | None = None
    nodata: float | None = None

    classes: list[str] | None = Field(
        default=None, description="Class names as stored, index-aligned to the values")
    class_descriptions: list[str | None] | None = Field(
        default=None,
        description="Readable name per class, index-aligned to `classes`; null keeps the stored name")
    class_scheme: str | None = Field(
        default=None, description="Canonical scheme these classes map onto")
    class_map: list[int] | None = Field(
        default=None, description="Native class index to canonical class index")
    ignore_index: int | None = Field(
        default=None, description="Class a loss must not score, such as unannotated pixels")
    ignore_classes: list[int] | None = Field(
        default=None, description="Further classes a loss must not score")

    crs_field: str | None = Field(default=None, description="Column holding this slot's CRS")
    time_field: str | None = Field(default=None, description="Column holding acquisition times")
    counts_field: str | None = Field(default=None, description="Column holding per-object counts")
    task_field: str | None = Field(default=None, description="Column naming the task of each record")
    frames_field: str | None = Field(default=None, description="Column holding the number of frames")
    optional: bool = Field(default=False, description="Whether samples may omit this slot")


class MLContract(CollectionModel):
    """What a model reads and what it predicts, for this collection."""

    __taco_namespace__ = "ml"

    inputs: list[Slot]
    targets: list[Slot] = Field(default_factory=list)
    tasks: list[str] = Field(
        default_factory=list, description="Tasks these target slots can serve")

    @model_validator(mode="after")
    def _stamp_roles(self) -> "MLContract":
        """Fill each slot's role from the list it appears in, and reject a mismatch."""
        for role, slots in (("input", self.inputs), ("target", self.targets)):
            for slot in slots:
                if slot.role is None:
                    object.__setattr__(slot, "role", role)
                elif slot.role != role:
                    raise ValueError(f"slot {slot.name!r} is declared {slot.role!r} "
                                     f"but appears under {role}s")
        return self


__all__ = ["Band", "Calibration", "MLContract", "Modality", "ProcessingLevel",
           "Slot", "SlotKind"]
