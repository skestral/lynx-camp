from __future__ import annotations

from types import SimpleNamespace

from backend.app.db import Store
from backend.app.scan_config import reset_scan_config, scan_config, update_scan_config
from backend.app.scanner import Scanner


def settings(**overrides):
    defaults = {
        "min_poll_interval_minutes": 10,
        "release_scan_before_minutes": 15,
        "release_scan_after_minutes": 60,
        "release_scan_interval_minutes": 10,
        "availability_cache_minutes": 5,
        "api_request_delay_seconds": 1.0,
        "rate_limit_backoff_minutes": 60,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class EmptyClient:
    pass


class NoopNotifier:
    pass


def test_scan_config_uses_environment_defaults(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    config = scan_config(store, settings(min_poll_interval_minutes=30, api_request_delay_seconds=2.5))

    assert config["values"]["min_poll_interval_minutes"] == 30
    assert config["values"]["api_request_delay_seconds"] == 2.5
    assert config["sources"]["min_poll_interval_minutes"] == "environment"
    assert config["environment"]["rate_limit_backoff_minutes"] == 60


def test_scan_config_persists_appdata_overrides(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    config = update_scan_config(
        store,
        settings(),
        {
            "min_poll_interval_minutes": 45,
            "availability_cache_minutes": 20,
            "api_request_delay_seconds": 2.25,
            "rate_limit_backoff_minutes": 180,
        },
    )

    assert config["values"]["min_poll_interval_minutes"] == 45
    assert config["values"]["availability_cache_minutes"] == 20
    assert config["values"]["api_request_delay_seconds"] == 2.25
    assert config["values"]["rate_limit_backoff_minutes"] == 180
    assert config["sources"]["min_poll_interval_minutes"] == "appdata"
    assert store.get_app_settings(["scan_min_poll_interval_minutes"]) == {"scan_min_poll_interval_minutes": "45"}


def test_scan_config_reset_returns_to_environment(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    update_scan_config(store, settings(), {"min_poll_interval_minutes": 45})

    config = reset_scan_config(store, settings(min_poll_interval_minutes=25))

    assert config["values"]["min_poll_interval_minutes"] == 25
    assert config["sources"]["min_poll_interval_minutes"] == "environment"
    assert store.get_app_settings(["scan_min_poll_interval_minutes"]) == {}


def test_scanner_applies_live_scan_controls(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    scanner = Scanner(store, EmptyClient(), NoopNotifier(), min_poll_interval_minutes=10)

    scanner.configure_scan_controls(
        min_poll_interval_minutes=30,
        release_scan_before_minutes=20,
        release_scan_after_minutes=90,
        release_scan_interval_minutes=15,
        availability_cache_minutes=25,
        api_request_delay_seconds=3,
        rate_limit_backoff_minutes=120,
    )

    assert scanner.min_poll_interval_minutes == 30
    assert scanner.release_scan_before_minutes == 20
    assert scanner.release_scan_after_minutes == 90
    assert scanner.release_scan_interval_minutes == 15
    assert scanner.availability_cache_minutes == 25
    assert scanner.api_request_delay_seconds == 3
    assert scanner.rate_limit_backoff_minutes == 120
