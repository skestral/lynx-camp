"""Saved, provider-independent coverage for regional watches."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RegionScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["state", "parks", "bounds"]
    state_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    park_names: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=100)
    south: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    west: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    north: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    east: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode="after")
    def complete_scope(self):
        bounds = (self.south, self.west, self.north, self.east)
        if self.kind == "state":
            valid = self.state_code and not self.park_names and all(value is None for value in bounds)
        elif self.kind == "parks":
            valid = self.park_names and not self.state_code and all(value is None for value in bounds)
            self.park_names = sorted(set(self.park_names))
        else:
            valid = (not self.state_code and not self.park_names and all(value is not None for value in bounds)
                     and self.south < self.north and self.west < self.east)
        if not valid:
            raise ValueError("Region requires one state, park groups, or ordered map bounds")
        return self


def matches_region(target: dict, scope: dict) -> bool:
    if scope["kind"] == "state":
        return str(target.get("state_code") or "").upper() == scope["state_code"]
    if scope["kind"] == "parks":
        return (target.get("park_name") or "Unassigned park") in scope["park_names"]
    latitude, longitude = target.get("latitude"), target.get("longitude")
    return (latitude is not None and longitude is not None
            and scope["south"] <= latitude <= scope["north"]
            and scope["west"] <= longitude <= scope["east"])
