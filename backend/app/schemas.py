from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from .provider_ids import provider_key
from .regions import RegionScope


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

    @field_validator("campground_id")
    @classmethod
    def known_provider(cls, value: str) -> str:
        provider_key(value)
        return value


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
    equipment: Literal["", "tent", "rv", "trailer", "vehicle"] = ""
    vehicle_length_ft: float | None = Field(default=None, gt=0, le=200, allow_inf_nan=False)
    campsite_ids: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("campsite_ids")
    @classmethod
    def valid_site_ids(cls, values):
        if any(not value or len(value) > 160 for value in values):
            raise ValueError("Invalid campsite selection")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def length_requires_vehicle(self):
        if self.vehicle_length_ft is not None and self.equipment not in {"rv", "trailer", "vehicle"}:
            raise ValueError("Choose RV, trailer, or vehicle when specifying its length")
        return self


class WatchBulkUpdate(BaseModel):
    action: Literal["pause", "resume", "delete"]
    watch_ids: list[int] = Field(min_length=1, max_length=2000)

    @field_validator("watch_ids")
    @classmethod
    def positive_watch_ids(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("watch_ids must be positive")
        return sorted(set(value))


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
    alerts_enabled: bool = False
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


class WatchGroupCreate(BaseModel):
    target_ids: list[int] = Field(min_length=1, max_length=500)
    watch: WatchCreate
    region_scope: RegionScope | None = None


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
    alerts_enabled: bool | None = None
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


class WatchGroupUpdate(WatchUpdate):
    region_scope: RegionScope | None = None


class ConfigRegion(BaseModel):
    group_id: str = Field(min_length=1, max_length=64)
    scope: RegionScope
    excluded_campgrounds: list[str] = Field(default_factory=list, max_length=10000)


class ConfigWatch(BaseModel):
    group_id: str | None = Field(default=None, max_length=64)
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
    alerts_enabled: bool = False
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


class ConfigSettings(BaseModel):
    app_settings: dict[str, str] = Field(default_factory=dict)
    redacted_keys: list[str] = Field(default_factory=list)

    @field_validator("app_settings")
    @classmethod
    def valid_notification_destinations(cls, values):
        from .app_settings import normalize_app_base_url
        from .apprise_alerts import validate_urls
        from .alert_schedule import validate_schedule
        validate_schedule({key.removeprefix("notification_"): value for key, value in values.items()})
        if values.get("notification_apprise_urls"):
            validate_urls(values["notification_apprise_urls"])
        if "notification_app_base_url" in values:
            values["notification_app_base_url"] = normalize_app_base_url(values["notification_app_base_url"])
        return values


class ConfigBackup(BaseModel):
    version: int = Field(default=1, ge=1)
    exported_at: str | None = None
    targets: list[ConfigTarget] = Field(default_factory=list)
    settings: ConfigSettings = Field(default_factory=ConfigSettings)
    regions: list[ConfigRegion] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_regions(self):
        seen = set()
        for region in self.regions:
            if region.group_id in seen:
                raise ValueError("Backup contains duplicate regional coverage definitions")
            seen.add(region.group_id)
            members = [watch for target in self.targets for watch in target.watches if watch.group_id == region.group_id]
            rules = [watch.model_dump(exclude={"active"}) for watch in members]
            if not rules or any(rule != rules[0] for rule in rules):
                raise ValueError("Saved region requires members with the same watch criteria")
        return self


class ResultStatusUpdate(BaseModel):
    status: Literal["available", "opened", "booked", "dismissed"]


class ResultGroupDismiss(BaseModel):
    result_ids: list[int] = Field(min_length=1, max_length=2000)

    @field_validator("result_ids")
    @classmethod
    def positive_result_ids(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("result_ids must be positive")
        return sorted(set(value))


class CartAssistConfigUpdate(BaseModel):
    enabled: bool | None = None
    cooldown_minutes: int | None = Field(default=None, ge=1, le=1440)
    max_attempts_per_scan: int | None = Field(default=None, ge=1, le=25)
    username: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=500)


class ScanConfigUpdate(BaseModel):
    min_poll_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    release_scan_before_minutes: int | None = Field(default=None, ge=0, le=1440)
    release_scan_after_minutes: int | None = Field(default=None, ge=0, le=1440)
    release_scan_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    availability_cache_minutes: int | None = Field(default=None, ge=0, le=1440)
    api_request_delay_seconds: float | None = Field(default=None, ge=0, le=60)
    rate_limit_backoff_minutes: int | None = Field(default=None, ge=1, le=1440)


class NotificationConfigUpdate(BaseModel):
    app_base_url: str | None = Field(default=None, max_length=2048)

    @field_validator("app_base_url")
    @classmethod
    def valid_app_base_url(cls, value):
        from .app_settings import normalize_app_base_url
        return normalize_app_base_url(value) if value is not None else None

    digest_frequency: Literal["daily", "weekly", "disabled"] | None = None
    digest_time: str | None = Field(default=None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    digest_timezone: Literal["America/Los_Angeles", "server", "UTC"] | None = None
    digest_weekday: int | None = Field(default=None, ge=0, le=6)
    home_assistant_errors_enabled: bool | None = None
    home_assistant_error_cooldown_minutes: int | None = Field(default=None, ge=1, le=10080)
    apprise_urls: str | None = Field(default=None, max_length=16000)

    @field_validator("apprise_urls")
    @classmethod
    def valid_apprise_urls(cls, value):
        from .apprise_alerts import validate_urls
        if value:
            validate_urls(value)
        return value

    webhook_url: str | None = Field(default=None, max_length=1000)
    home_assistant_webhook_url: str | None = Field(default=None, max_length=1000)
    ntfy_server: str | None = Field(default=None, max_length=500)
    ntfy_topic: str | None = Field(default=None, max_length=300)
    ntfy_token: str | None = Field(default=None, max_length=1000)
    ntfy_priority: str | None = Field(default=None, max_length=40)
    smtp_host: str | None = Field(default=None, max_length=300)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=300)
    smtp_password: str | None = Field(default=None, max_length=1000)
    smtp_from: str | None = Field(default=None, max_length=300)
    smtp_to: str | None = Field(default=None, max_length=500)
    max_notification_results: int | None = Field(default=None, ge=1, le=100)


class CartAttemptStatusUpdate(BaseModel):
    status: Literal["manual_required", "opened", "booked", "dismissed", "failed"]
    message: str | None = Field(default=None, max_length=500)
