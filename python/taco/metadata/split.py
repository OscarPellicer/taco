from typing import Literal

from pydantic import Field

from ._base import SampleModel


class Split(SampleModel):
    split: Literal["train", "test", "validation", "excluded"] = Field(
        description="Dataset split. `excluded` is held out of every partition"
    )


class SplitProvenance(SampleModel):
    """How a sample's split was assigned and alternative splits."""

    original: str | None = Field(
        default=None,
        description="The publisher's original split name, before normalising it to "
                    "train / validation / test / excluded",
    )
    noleak: Literal["train", "test", "validation", "excluded"] | None = Field(
        default=None,
        description="Alternative split, disjoint across collections that share imagery",
    )
    noleak_rule: str | None = Field(
        default=None,
        description="Versioned rule that produced `noleak` split, as `<namespace>/<rule>-v<n>`",
    )


__all__ = ["Split", "SplitProvenance"]
