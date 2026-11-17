"""Validate the submitted search, not an edited form with stale results below it."""
from datetime import date
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


HOST = "washington.goingtocamp.com"


class InspectionError(ValueError):
    pass


class ExpectedSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    park: str = Field(min_length=1, max_length=160)
    resource_location_id: str = Field(pattern=r"^-?[0-9]{1,10}$")
    category: Literal["Camping", "Roofed"]
    arrival: date
    departure: date

    @model_validator(mode="after")
    def validate_stay(self):
        if not 1 <= (self.departure - self.arrival).days <= 31:
            raise ValueError("Expected stay must be between one and 31 nights")
        if self.park != self.park.strip():
            raise ValueError("Park name must not have surrounding whitespace")
        return self

    def results_label(self) -> str:
        def label(day):
            return f"{day:%A}, {day:%B} {day.day}, {day.year}"
        return f"Search results for {label(self.arrival)} and {label(self.departure)}"


def is_provider_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname == HOST and parsed.port in (None, 443)
                and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


def validate_submitted_search(url: str, expected: ExpectedSearch) -> dict:
    if not is_provider_url(url):
        raise InspectionError("Open the normal Washington reservation results page first")
    parsed = urlsplit(url)
    if parsed.path != "/create-booking/results":
        raise InspectionError("Open the normal Washington reservation results page first")
    params = parse_qs(parsed.query, keep_blank_values=True)
    category = "0" if expected.category == "Camping" else "1"
    required = {
        "resourceLocationId": expected.resource_location_id,
        "bookingCategoryId": category, "searchTabGroupId": category,
        "startDate": expected.arrival.isoformat(), "endDate": expected.departure.isoformat(),
        "nights": str((expected.departure - expected.arrival).days), "isReserving": "true", "view": "list",
    }
    if any(params.get(key) != [value] for key, value in required.items()):
        raise InspectionError("Submitted search does not match the expected park, category, dates, or list view")
    return required
