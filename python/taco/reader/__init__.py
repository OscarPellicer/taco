"""Read TACO datasets and inspect their contracts."""

from . import inspect
from .api import Dataset, open_dataset, read

__all__ = [
    "Dataset",
    "inspect",
    "open_dataset",
    "read",
]
