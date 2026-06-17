from __future__ import annotations

import asyncio
from datetime import date

import httpx

from backend.app.recreation import Campsite, RecreationClient


def test_campsite_from_api_extracts_reservation_window() -> None:
    campsite = Campsite.from_api(
        {
            "campsite_id": "2560",
            "site": "D016",
            "loop": "A-F",
            "campsite_type": "STANDARD NONELECTRIC",
            "max_num_people": 8,
            "availabilities": {},
            "campsite_rules": {
                "reservationWindow": {
                    "value": 14,
                    "units": "Days",
                }
            },
        }
    )

    assert campsite.reservation_window_value == 14
    assert campsite.reservation_window_unit == "Days"


def test_search_campgrounds_parses_recreation_search_results() -> None:
    class FakeClient(RecreationClient):
        def __init__(self):
            super().__init__()
            self.calls = []

        async def _get(self, path, params):
            self.calls.append((path, params))
            return {
                "results": [
                    {
                        "entity_type": "campground",
                        "entity_id": "247592",
                        "name": "HOH RAINFOREST CAMPGROUND",
                        "parent_name": "Olympic National Park",
                        "state_code": "Washington",
                        "latitude": "47.85835250000000",
                        "longitude": "-123.93554010000000",
                    },
                    {
                        "entity_type": "recarea",
                        "entity_id": "2881",
                        "name": "Olympic National Park",
                    },
                ]
            }

    client = FakeClient()
    results = asyncio.run(client.search_campgrounds("Olympic National Park", size=100, start=200))

    assert client.calls == [
        (
            "/search",
            {
                "fq": ["entity_type:campground"],
                "q": "Olympic National Park",
                "size": "100",
                "start": "200",
            },
        )
    ]
    assert results == [
        {
            "name": "Hoh Rainforest Campground",
            "campground_id": "247592",
            "park_name": "Olympic National Park",
            "state_code": "WA",
            "latitude": "47.85835250000000",
            "longitude": "-123.93554010000000",
        }
    ]


def test_campground_details_normalizes_recreation_payload() -> None:
    class FakeClient(RecreationClient):
        async def _get(self, path, params):
            assert path == "/camps/campgrounds/232464"
            assert params == {}
            return {
                "campground": {
                    "facility_id": "232464",
                    "facility_name": "KALALOCH",
                    "facility_description_map": {
                        "Overview": "<p><strong>Ocean bluff</strong> campground.</p>",
                        "Facilities": "<p>160 campsites<br>Flush toilets</p>",
                    },
                    "facility_directions": "On Highway 101.",
                    "facility_phone": "360-565-3130",
                    "facility_latitude": 47.6,
                    "facility_longitude": -124.3,
                    "facility_time_zone": "America/Los_Angeles",
                    "amenities": {"Flush Toilets": "Flush Toilets", "Water": "Water"},
                    "activities": [{"activity_name": "Hiking"}, {"activity_name": "Camping"}],
                    "addresses": [
                        {
                            "address1": "HWY 101",
                            "city": "Forks",
                            "state_code": "WA",
                            "postal_code": "98331",
                        }
                    ],
                    "notices": [{"notice_text": "<p>Valid pass required.</p>", "active": True}],
                    "links": [{"title": "Park page", "url": "https://example.com"}],
                    "media": [{"image_url": "https://example.com/kalaloch.jpg"}],
                }
            }

    details = asyncio.run(FakeClient().campground_details("232464"))

    assert details is not None
    assert details["name"] == "Kalaloch"
    assert details["description"] == "Ocean bluff campground."
    assert details["facilities"] == "160 campsites Flush toilets"
    assert details["address"] == "HWY 101, Forks, WA, 98331"
    assert details["amenities"] == ["Flush Toilets", "Water"]
    assert details["activities"] == ["Camping", "Hiking"]
    assert details["notices"] == ["Valid pass required."]
    assert details["image_url"] == "https://example.com/kalaloch.jpg"


def test_campground_details_returns_none_for_missing_detail_record() -> None:
    class FakeClient(RecreationClient):
        async def _get(self, path, params):
            request = httpx.Request("GET", f"https://www.recreation.gov/api{path}")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("missing", request=request, response=response)

    details = asyncio.run(FakeClient().campground_details("10300477"))

    assert details is None


def test_detect_release_window_uses_most_common_window() -> None:
    class FakeClient(RecreationClient):
        async def monthly_availability(self, campground_id: str, month: date) -> dict[str, Campsite]:
            return {
                "1": Campsite(
                    campsite_id="1",
                    site="A1",
                    loop="A",
                    campsite_type="Tent",
                    max_num_people=4,
                    availabilities={},
                    reservation_window_value=14,
                    reservation_window_unit="Days",
                ),
                "2": Campsite(
                    campsite_id="2",
                    site="A2",
                    loop="A",
                    campsite_type="Tent",
                    max_num_people=4,
                    availabilities={},
                    reservation_window_value=14,
                    reservation_window_unit="Days",
                ),
                "3": Campsite(
                    campsite_id="3",
                    site="A3",
                    loop="A",
                    campsite_type="Tent",
                    max_num_people=4,
                    availabilities={},
                    reservation_window_value=6,
                    reservation_window_unit="Months",
                ),
            }

    detected = asyncio.run(FakeClient().detect_release_window("232464", date(2026, 7, 1)))

    assert detected == {
        "release_window_value": 14,
        "release_window_unit": "Days",
        "sampled_month": "2026-07-01",
        "source_campsite_count": 2,
        "total_campsite_count": 3,
    }


def test_release_window_profiles_group_by_loop_type_and_window() -> None:
    class FakeClient(RecreationClient):
        async def monthly_availability(self, campground_id: str, month: date) -> dict[str, Campsite]:
            return {
                "1": Campsite(
                    campsite_id="1",
                    site="C1",
                    loop="C",
                    campsite_type="Tent",
                    max_num_people=4,
                    availabilities={},
                    reservation_window_value=14,
                    reservation_window_unit="Days",
                ),
                "2": Campsite(
                    campsite_id="2",
                    site="C2",
                    loop="C",
                    campsite_type="Tent",
                    max_num_people=4,
                    availabilities={},
                    reservation_window_value=14,
                    reservation_window_unit="Days",
                ),
                "3": Campsite(
                    campsite_id="3",
                    site="D1",
                    loop="D",
                    campsite_type="Tent",
                    max_num_people=4,
                    availabilities={},
                    reservation_window_value=4,
                    reservation_window_unit="Days",
                ),
            }

    profiles = asyncio.run(FakeClient().release_window_profiles("247591", date(2026, 7, 1)))

    assert profiles == {
        "sampled_month": "2026-07-01",
        "total_campsite_count": 3,
        "profiles": [
            {
                "loop": "C",
                "campsite_type": "Tent",
                "release_window_value": 14,
                "release_window_unit": "Days",
                "campsite_count": 2,
            },
            {
                "loop": "D",
                "campsite_type": "Tent",
                "release_window_value": 4,
                "release_window_unit": "Days",
                "campsite_count": 1,
            },
        ],
    }
