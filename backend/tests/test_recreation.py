from __future__ import annotations

import asyncio
from datetime import date

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
