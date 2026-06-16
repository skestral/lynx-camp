from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _float_env(name: str, default: str) -> float:
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path(os.getenv("CAMPFINDER_DB", ROOT_DIR / "data" / "campfinder.db"))
    static_dir: Path = Path(os.getenv("CAMPFINDER_STATIC_DIR", ROOT_DIR / "frontend" / "dist"))
    app_base_url: str = os.getenv("CAMPFINDER_APP_BASE_URL", "http://localhost:8080")
    scan_loop_seconds: int = int(os.getenv("CAMPFINDER_SCAN_LOOP_SECONDS", "30"))
    min_poll_interval_minutes: int = int(os.getenv("CAMPFINDER_MIN_POLL_INTERVAL_MINUTES", "10"))
    release_scan_before_minutes: int = int(os.getenv("CAMPFINDER_RELEASE_SCAN_BEFORE_MINUTES", "15"))
    release_scan_after_minutes: int = int(os.getenv("CAMPFINDER_RELEASE_SCAN_AFTER_MINUTES", "60"))
    release_scan_interval_minutes: int = int(os.getenv("CAMPFINDER_RELEASE_SCAN_INTERVAL_MINUTES", "10"))
    availability_cache_minutes: int = int(os.getenv("CAMPFINDER_AVAILABILITY_CACHE_MINUTES", "5"))
    api_request_delay_seconds: float = _float_env("CAMPFINDER_API_REQUEST_DELAY_SECONDS", "1")
    rate_limit_backoff_minutes: int = int(os.getenv("CAMPFINDER_RATE_LIMIT_BACKOFF_MINUTES", "60"))
    max_notification_results: int = int(os.getenv("CAMPFINDER_MAX_NOTIFICATION_RESULTS", "5"))
    webhook_url: str | None = _optional_env("CAMPFINDER_WEBHOOK_URL")
    ntfy_server: str = os.getenv("CAMPFINDER_NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    ntfy_topic: str | None = _optional_env("CAMPFINDER_NTFY_TOPIC")
    ntfy_token: str | None = _optional_env("CAMPFINDER_NTFY_TOKEN")
    ntfy_priority: str = os.getenv("CAMPFINDER_NTFY_PRIORITY", "high")
    smtp_host: str | None = _optional_env("CAMPFINDER_SMTP_HOST")
    smtp_port: int = int(os.getenv("CAMPFINDER_SMTP_PORT", "587"))
    smtp_username: str | None = _optional_env("CAMPFINDER_SMTP_USERNAME")
    smtp_password: str | None = _optional_env("CAMPFINDER_SMTP_PASSWORD")
    smtp_from: str | None = _optional_env("CAMPFINDER_SMTP_FROM")
    smtp_to: str | None = _optional_env("CAMPFINDER_SMTP_TO")


settings = Settings()
