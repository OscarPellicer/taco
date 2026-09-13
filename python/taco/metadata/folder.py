from typing import ClassVar

from .sample import ISTAC as _SampleISTAC
from .sample import STAC as _SampleSTAC
from .sample import ISpatial as _SampleISpatial
from .sample import Spatial as _SampleSpatial
from .sample import Temporal as _SampleTemporal


class Spatial(_SampleSpatial):
    __taco_scopes__: ClassVar[frozenset[str]] = frozenset({"folder"})


class ISpatial(_SampleISpatial):
    __taco_scopes__: ClassVar[frozenset[str]] = frozenset({"folder"})


class Temporal(_SampleTemporal):
    __taco_scopes__: ClassVar[frozenset[str]] = frozenset({"folder"})


class STAC(_SampleSTAC):
    __taco_scopes__: ClassVar[frozenset[str]] = frozenset({"folder"})


class ISTAC(_SampleISTAC):
    __taco_scopes__: ClassVar[frozenset[str]] = frozenset({"folder"})


__all__ = ["ISTAC", "STAC", "ISpatial", "Spatial", "Temporal"]
