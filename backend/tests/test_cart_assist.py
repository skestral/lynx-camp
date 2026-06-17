from __future__ import annotations

from types import SimpleNamespace

from backend.app.cart_assist import CartAssistant
from backend.app.db import Store


def settings(**overrides):
    defaults = {
        "cart_assist_enabled": False,
        "cart_assist_cooldown_minutes": 30,
        "cart_assist_max_attempts_per_scan": 1,
        "recreation_gov_username": None,
        "recreation_gov_password": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def create_result(store: Store) -> dict:
    target = store.create_target(
        {
            "name": "Kalaloch",
            "campground_id": "232464",
            "park_name": "Olympic National Park",
            "state_code": "WA",
            "release_months": 6,
            "release_time": "07:00",
            "timezone": "America/Los_Angeles",
            "poll_interval_minutes": 10,
        }
    )
    watch = store.create_watch(
        {
            "target_id": target["id"],
            "name": "High priority weekend",
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-08-31",
            "specific_ranges": [],
            "cart_assist_enabled": True,
        }
    )
    result, _created = store.upsert_result(
        {
            "watch_id": watch["id"],
            "target_id": target["id"],
            "campground_id": "232464",
            "campground_name": "Kalaloch",
            "campsite_id": "101",
            "site": "A01",
            "loop": "A",
            "campsite_type": "Tent",
            "arrival_date": "2026-07-03",
            "departure_date": "2026-07-05",
            "booking_url": "https://www.recreation.gov/camping/campsites/101",
        }
    )
    return result


def test_cart_assist_status_does_not_expose_stored_credentials(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    assistant = CartAssistant(store, settings())

    status = assistant.update_config(
        {
            "enabled": True,
            "cooldown_minutes": 12,
            "max_attempts_per_scan": 2,
            "username": "camper@example.com",
            "password": "secret",
        }
    )

    assert status["enabled"] is True
    assert status["ready"] is True
    assert status["guard_state"] == "ready"
    assert status["credentials_configured"] is True
    assert status["recent_actionable_attempt_count"] == 0
    assert status["next_allowed_at"] is None
    assert status["cooldown_remaining_minutes"] == 0
    assert status["active_attempt_count"] == 0
    assert status["ready_attempt_count"] == 0
    assert status["blocked_attempt_count"] == 0
    assert status["resolved_attempt_count"] == 0
    assert status["total_attempt_count"] == 0
    assert status["latest_active_attempt_at"] is None
    assert status["attempt_status_counts"] == {}
    assert status["credential_source"] == "appdata"
    assert status["cooldown_minutes"] == 12
    assert status["max_attempts_per_scan"] == 2
    assert "username" not in status
    assert "password" not in status
    assert store.get_app_settings(["recreation_gov_password"]) == {"recreation_gov_password": "secret"}


def test_cart_assist_clear_credentials_falls_back_to_environment(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    assistant = CartAssistant(
        store,
        settings(
            cart_assist_enabled=True,
            recreation_gov_username="env@example.com",
            recreation_gov_password="env-secret",
        ),
    )
    assistant.update_config({"username": "stored@example.com", "password": "stored-secret"})

    status = assistant.clear_credentials()

    assert status["ready"] is True
    assert status["guard_state"] == "ready"
    assert status["credentials_configured"] is True
    assert status["credential_source"] == "environment"
    assert store.get_app_settings(["recreation_gov_username", "recreation_gov_password"]) == {}


def test_cart_assist_status_reports_missing_credentials_guard_state(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    assistant = CartAssistant(store, settings())

    status = assistant.update_config({"enabled": True})

    assert status["enabled"] is True
    assert status["ready"] is False
    assert status["guard_state"] == "needs_credentials"
    assert status["credentials_configured"] is False


def test_cart_assist_status_reports_cooldown_guard_state(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    assistant = CartAssistant(
        store,
        settings(
            cart_assist_enabled=True,
            recreation_gov_username="camper@example.com",
            recreation_gov_password="secret",
        ),
    )
    result = create_result(store)
    store.record_cart_attempt(result, "manual_required", "Ready for manual checkout.")

    status = assistant.status()

    assert status["enabled"] is True
    assert status["credentials_configured"] is True
    assert status["ready"] is False
    assert status["guard_state"] == "cooldown"
    assert status["recent_actionable_attempt_count"] == 1
    assert status["latest_actionable_attempt_at"] is not None
    assert status["next_allowed_at"] is not None
    assert status["cooldown_remaining_minutes"] > 0
    assert status["active_attempt_count"] == 1
    assert status["ready_attempt_count"] == 1
    assert status["blocked_attempt_count"] == 0
    assert status["resolved_attempt_count"] == 0
    assert status["total_attempt_count"] == 1
    assert status["latest_active_attempt_at"] is not None
    assert status["attempt_status_counts"] == {"manual_required": 1}
