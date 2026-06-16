from __future__ import annotations

from datetime import UTC, date, datetime

from backend.app.recreation import Campsite
from backend.app.scanner import (
    compute_release_at,
    find_available_sites,
    generate_trip_windows,
    months_for_trip,
    release_hints,
    release_scan_delay_minutes,
    required_night_keys,
    site_matches_filters,
)


def test_required_nights_are_departure_exclusive() -> None:
    nights = required_night_keys(date(2026, 7, 3), date(2026, 7, 5))

    assert nights == ["2026-07-03T00:00:00Z", "2026-07-04T00:00:00Z"]


def test_weekend_pattern_generates_friday_arrivals() -> None:
    watch = {
        "mode": "weekend",
        "pattern": "fri-sun",
        "nights": 2,
        "window_start": "2026-07-01",
        "window_end": "2026-07-20",
    }

    trips = generate_trip_windows(watch)

    assert [(trip.arrival_date.isoformat(), trip.departure_date.isoformat()) for trip in trips] == [
        ("2026-07-03", "2026-07-05"),
        ("2026-07-10", "2026-07-12"),
        ("2026-07-17", "2026-07-19"),
    ]


def test_arrival_weekdays_override_pattern() -> None:
    watch = {
        "mode": "weekend",
        "pattern": "fri-sun",
        "arrival_weekdays": [3, 4],
        "nights": 3,
        "window_start": "2026-07-01",
        "window_end": "2026-07-12",
    }

    trips = generate_trip_windows(watch)

    assert [(trip.arrival_date.isoformat(), trip.departure_date.isoformat()) for trip in trips] == [
        ("2026-07-02", "2026-07-05"),
        ("2026-07-03", "2026-07-06"),
        ("2026-07-09", "2026-07-12"),
    ]


def test_months_for_trip_crosses_month_boundary() -> None:
    months = months_for_trip(date(2026, 7, 31), date(2026, 8, 2))

    assert months == [date(2026, 7, 1), date(2026, 8, 1)]


def test_find_available_sites_requires_all_nights() -> None:
    available_site = Campsite(
        campsite_id="101",
        site="A01",
        loop="A",
        campsite_type="Tent",
        max_num_people=4,
        availabilities={
            "2026-07-03T00:00:00Z": "Available",
            "2026-07-04T00:00:00Z": "Available",
        },
    )
    partial_site = Campsite(
        campsite_id="102",
        site="A02",
        loop="A",
        campsite_type="Tent",
        max_num_people=4,
        availabilities={
            "2026-07-03T00:00:00Z": "Available",
            "2026-07-04T00:00:00Z": "Reserved",
        },
    )

    sites = find_available_sites([{"101": available_site, "102": partial_site}], date(2026, 7, 3), date(2026, 7, 5))

    assert [site.campsite_id for site in sites] == ["101"]


def test_site_matches_filters_checks_type_loop_site_and_people() -> None:
    campsite = Campsite(
        campsite_id="101",
        site="A12",
        loop="River Loop",
        campsite_type="Tent Only",
        max_num_people=6,
        availabilities={},
    )

    assert site_matches_filters(campsite, {"site_type": "tent", "loop": "river", "site": "A", "min_people": 4})
    assert not site_matches_filters(campsite, {"site_type": "rv"})
    assert not site_matches_filters(campsite, {"loop": "meadow"})
    assert not site_matches_filters(campsite, {"site": "B"})
    assert not site_matches_filters(campsite, {"min_people": 8})


def test_compute_release_at_uses_target_timezone_and_month_window() -> None:
    target = {
        "release_months": 6,
        "release_time": "07:00",
        "timezone": "America/Los_Angeles",
    }

    release_at = compute_release_at(date(2026, 7, 3), target)

    assert release_at.isoformat() == "2026-01-03T07:00:00-08:00"


def test_compute_release_at_uses_day_window() -> None:
    target = {
        "release_window_value": 14,
        "release_window_unit": "Days",
        "release_time": "07:00",
        "timezone": "America/Los_Angeles",
    }

    release_at = compute_release_at(date(2026, 7, 3), target)

    assert release_at.isoformat() == "2026-06-19T07:00:00-07:00"


def test_compute_release_at_uses_week_window() -> None:
    target = {
        "release_window_value": 2,
        "release_window_unit": "Weeks",
        "release_time": "07:00",
        "timezone": "America/Los_Angeles",
    }

    release_at = compute_release_at(date(2026, 7, 3), target)

    assert release_at.isoformat() == "2026-06-19T07:00:00-07:00"


def test_release_hints_include_already_open_trips() -> None:
    watch = {
        "mode": "weekend",
        "pattern": "fri-sun",
        "arrival_weekdays": [4],
        "nights": 2,
        "window_start": "2035-07-01",
        "window_end": "2035-07-12",
        "release_months": 6,
        "release_time": "07:00",
        "timezone": "America/Los_Angeles",
    }

    hints = release_hints(watch)

    assert hints[0]["arrival_date"] == "2035-07-06"
    assert hints[0]["release_status"] in {"open", "upcoming"}


def test_release_scan_delay_uses_normal_interval_outside_release_window() -> None:
    watch = {
        "mode": "specific",
        "specific_ranges": [{"arrival_date": "2026-07-03", "departure_date": "2026-07-05"}],
        "release_months": 6,
        "release_time": "07:00",
        "timezone": "America/Los_Angeles",
    }

    delay = release_scan_delay_minutes(
        watch,
        normal_interval_minutes=60,
        min_poll_interval_minutes=10,
        now=datetime(2026, 1, 3, 13, 0, tzinfo=UTC),
        before_minutes=15,
        after_minutes=60,
        boost_interval_minutes=2,
    )

    assert delay == 60


def test_release_scan_delay_wakes_up_before_release_window() -> None:
    watch = {
        "mode": "specific",
        "specific_ranges": [{"arrival_date": "2026-07-03", "departure_date": "2026-07-05"}],
        "release_months": 6,
        "release_time": "07:00",
        "timezone": "America/Los_Angeles",
    }

    delay = release_scan_delay_minutes(
        watch,
        normal_interval_minutes=60,
        min_poll_interval_minutes=10,
        now=datetime(2026, 1, 3, 14, 30, tzinfo=UTC),
        before_minutes=15,
        after_minutes=60,
        boost_interval_minutes=2,
    )

    assert delay == 15


def test_release_scan_delay_uses_boost_interval_during_release_window() -> None:
    watch = {
        "mode": "specific",
        "specific_ranges": [{"arrival_date": "2026-07-03", "departure_date": "2026-07-05"}],
        "release_months": 6,
        "release_time": "07:00",
        "timezone": "America/Los_Angeles",
    }

    delay = release_scan_delay_minutes(
        watch,
        normal_interval_minutes=60,
        min_poll_interval_minutes=10,
        now=datetime(2026, 1, 3, 14, 58, tzinfo=UTC),
        before_minutes=15,
        after_minutes=60,
        boost_interval_minutes=2,
    )

    assert delay == 2
