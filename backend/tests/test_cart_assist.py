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
    assert status["credentials_configured"] is True
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
    assert status["credentials_configured"] is True
    assert status["credential_source"] == "environment"
    assert store.get_app_settings(["recreation_gov_username", "recreation_gov_password"]) == {}
