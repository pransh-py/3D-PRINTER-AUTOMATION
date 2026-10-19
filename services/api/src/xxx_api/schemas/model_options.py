"""Explicit, bounded transforms for unitless mesh sources."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class ModelOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source_unit: Literal["mm", "inch"] = Field(default="mm", alias="sourceUnit")
    rotation_x: StrictInt = Field(default=0, ge=-180, le=180, alias="rotationX")
    rotation_y: StrictInt = Field(default=0, ge=-180, le=180, alias="rotationY")

    @property
    def is_identity(self) -> bool:
        return self.source_unit == "mm" and self.rotation_x == 0 and self.rotation_y == 0
