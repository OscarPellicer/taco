from typing import ClassVar

from .sample import ISAC as _SampleISAC
from .sample import ISTAC as _SampleISTAC
from .sample import SAC as _SampleSAC
from .sample import STAC as _SampleSTAC
from .sample import TAC as _SampleTAC


class SAC(_SampleSAC):
    __taco_scopes__: ClassVar[frozenset[str]] = frozenset({"folder"})


class ISAC(_SampleISAC):
    __taco_scopes__: ClassVar[frozenset[str]] = frozenset({"folder"})


class TAC(_SampleTAC):
    __taco_scopes__: ClassVar[frozenset[str]] = frozenset({"folder"})


class STAC(_SampleSTAC):
    __taco_scopes__: ClassVar[frozenset[str]] = frozenset({"folder"})


class ISTAC(_SampleISTAC):
    __taco_scopes__: ClassVar[frozenset[str]] = frozenset({"folder"})


__all__ = ["ISAC", "ISTAC", "SAC", "STAC", "TAC"]
