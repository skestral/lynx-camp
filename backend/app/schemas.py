from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DateRange(BaseModel):
    arrival_date: date
    departure_date: date

    @field_validator("departure_date")
    @classmethod
    def departure_after_arrival(cls, value: date, info):
        arrival = info.data.get("arrival_date")
        if arrival and value <= arrival:
            raise ValueError("departure_date must be after arrival_date")
        return value


class TargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    campground_id: str = Field(min_length=1, max_length=40)
    park_name: str = ""
    state_code: str = ""
    latitude: float | None = None
    longitude: float | None = None
    booking_url: str | None = None
    release_months: int = Field(default=6, ge=0, le=24)
    release_window_value: int = Field(default=6, ge=0, le=730)
    release_window_unit: Literal["Days", "Weeks", "Months"] = "Months"
    release_time: str = "07:00"
    timezone: str = "America/Los_Angeles"
    poll_interval_minutes: int = Field(default=10, ge=1, le=1440)
    active: bool = True


class TargetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    park_name: str | None = None
    state_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    booking_url: str | None = None
    release_months: int | None = Field(default=None, ge=0, le=24)
    release_window_value: int | None = Field(default=None, ge=0, le=730)
    release_window_unit: Literal["Days", "Weeks", "Months"] | None = None
    release_time: str | None = None
    timezone: str | None = None
    poll_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    active: bool | None = None


class SiteFilters(BaseModel):
    site_type: str = Field(default="", max_length=80)
    loop: str = Field(default="", max_length=80)
    site: str = Field(default="", max_length=80)
    min_people: int | None = Field(default=None, ge=1, le=99)


class WatchCreate(BaseModel):
    target_id: int
    name: str = Field(min_length=1, max_length=120)
    mode: Literal["weekend", "specific"]
    pattern: str = "fri-sun"
    arrival_weekdays: list[int] | None = None
    nights: int = Field(default=2, ge=1, le=14)
    window_start: date
    window_end: date
    site_filters: SiteFilters = Field(default_factory=SiteFilters)
    specific_ranges: list[DateRange] = Field(default_factory=list)
    cart_assist_enabled: bool = False
    active: bool = True

    @field_validator("window_end")
    @classmethod
    def window_end_after_start(cls, value: date, info):
        start = info.data.get("window_start")
        if start and value < start:
            raise ValueError("window_end must be on or after window_start")
        return value

    @field_validator("arrival_weekdays")
    @classmethod
    def valid_arrival_weekdays(cls, value: list[int] | None):
        if value is None:
            return value
        unique = sorted(set(value))
        if not unique:
            raise ValueError("arrival_weekdays must include at least one day")
        if any(day < 0 or day > 6 for day in unique):
            raise ValueError("arrival_weekdays values must be 0 through 6")
        return unique


class WatchUpdate(BaseModel):
    target_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    mode: Literal["weekend", "specific"] | None = None
    pattern: str | None = None
    arrival_weekdays: list[int] | None = None
    nights: int | None = Field(default=None, ge=1, le=14)
    window_start: date | None = None
    window_end: date | None = None
    site_filters: SiteFilters | None = None
    specific_ranges: list[DateRange] | None = None
    cart_assist_enabled: bool | None = None
    active: bool | None = None

    @field_validator("arrival_weekdays")
    @classmethod
    def valid_arrival_weekdays(cls, value: list[int] | None):
        if value is None:
            return value
        unique = sorted(set(value))
        if not unique:
            raise ValueError("arrival_weekdays must include at least one day")
        if any(day < 0 or day > 6 for day in unique):
            raise ValueError("arrival_weekdays values must be 0 through 6")
        return unique


class ConfigWatch(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    mode: Literal["weekend", "specific"]
    pattern: str = "fri-sun"
    arrival_weekdays: list[int] | None = None
    nights: int = Field(default=2, ge=1, le=14)
    window_start: date
    window_end: date
    site_filters: SiteFilters = Field(default_factory=SiteFilters)
    specific_ranges: list[DateRange] = Field(default_factory=list)
    cart_assist_enabled: bool = False
    active: bool = True

    @field_validator("window_end")
    @classmethod
    def window_end_after_start(cls, value: date, info):
        start = info.data.get("window_start")
        if start and value < start:
            raise ValueError("window_end must be on or after window_start")
        return value

    @field_validator("arrival_weekdays")
    @classmethod
    def valid_arrival_weekdays(cls, value: list[int] | None):
        if value is None:
            return value
        unique = sorted(set(value))
        if not unique:
            raise ValueError("arrival_weekdays must include at least one day")
        if any(day < 0 or day > 6 for day in unique):
            raise ValueError("arrival_weekdays values must be 0 through 6")
        return unique


class ConfigTarget(TargetCreate):
    watches: list[ConfigWatch] = Field(default_factory=list)


class ConfigBackup(BaseModel):
    version: int = Field(default=1, ge=1)
    exported_at: str | None = None
    targets: list[ConfigTarget] = Field(default_factory=list)


class ResultStatusUpdate(BaseModel):
    status: Literal["available", "opened", "booked", "dismissed"]
