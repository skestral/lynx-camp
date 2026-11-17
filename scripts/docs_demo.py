"""Serve a read-only screenshot demo without live scans or notifications."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(port: int) -> None:
    # Do not inherit personal settings or open the normal application database.
    for key in list(os.environ):
        if key.startswith("CAMPFINDER_"):
            del os.environ[key]
    with tempfile.TemporaryDirectory(prefix="campfinder-docs-") as directory:
        os.environ["CAMPFINDER_DB"] = str(Path(directory) / "demo.db")
        os.environ["CAMPFINDER_APP_BASE_URL"] = f"http://localhost:{port}"

        import uvicorn
        from fastapi.responses import JSONResponse
        from backend.app import main

        class OfflineClient:
            def __getattr__(self, name):
                async def unavailable(*args, **kwargs):
                    raise RuntimeError("Live provider requests are disabled in the documentation demo.")
                return unavailable

        main.client = OfflineClient()
        main.scanner.client = main.client
        main.store.init()
        targets = [main.store.create_target({
            "name": name, "park_name": park, "campground_id": f"demo-{index}",
            "state_code": "WA", "latitude": lat, "longitude": lon,
            "poll_interval_minutes": 60,
        }, min_poll_interval_minutes=60) for index, (name, park, lat, lon) in enumerate([
            ("Coast Campground", "Demo Olympic Coast", 47.6, -124.3),
            ("Forest Cabins", "Demo Olympic Coast", 47.8, -123.9),
            ("River Campground", "Demo Cascades", 48.5, -121.6),
            ("Mountain Campground", "Demo Cascades", 46.8, -121.7),
        ])]
        year = date.today().year + 1
        watches = main.store.create_watch_group([target["id"] for target in targets], {
            "name": "Washington weekends (demo)", "mode": "weekend",
            "arrival_weekdays": [4], "nights": 2,
            "window_start": f"{year}-07-01", "window_end": f"{year}-08-31",
            "site_filters": {}, "specific_ranges": [],
        }, region_scope={"kind": "state", "state_code": "WA"})
        for index, watch in enumerate(watches[:2]):
            for day in (2, 9):
                result, _ = main.store.upsert_result({
                    "watch_id": watch["id"], "target_id": watch["target_id"],
                    "campground_id": watch["campground_id"], "campground_name": watch["target_name"],
                    "campsite_id": f"demo-{index}-{day}", "site": "C01" if index else "A12",
                    "loop": "Forest" if index else "Coast", "campsite_type": "CABIN NONELECTRIC" if index else "TENT ONLY NONELECTRIC",
                    "arrival_date": f"{year}-07-{day:02d}", "departure_date": f"{year}-07-{day + 2:02d}",
                })
                main.store.record_notification(result["id"], "webhook", "sent", "Demo delivery record; no message was sent.")
            run_id = main.store.start_scan_run(watch)
            main.store.finish_scan_run(run_id, "success", "Demo check: two matching stays found.", 9, 2)
            main.store.log_scan_event(run_id, watch["id"], watch["target_id"], "info", "finished", "Demo check completed; two new matches saved.")
            main.store.schedule_next_scan(watch["id"], 60)
        watch = watches[2]
        run_id = main.store.start_scan_run(watch)
        main.store.finish_scan_run(run_id, "rate_limited", "Demo HTTP 429: pending checks retained until cooldown ends.", 9, 0)
        main.store.log_scan_event(run_id, watch["id"], watch["target_id"], "warning", "rate_limited", "Demo HTTP 429: crawl waiting; no further availability requests during cooldown.")
        main.notifier.update_config({"webhook_url": "https://discord.example.invalid/demo"})
        main.apply_scan_config()
        main.scanner._begin_full_scan(watches)
        main.scanner._sweep.update(status="waiting", pending=[w["id"] for w in watches[2:]], completed_count=2)
        main.scanner._adaptive_delay = 10
        main.scanner._api_backoff_until = datetime.now(UTC) + timedelta(minutes=40)
        main.scanner._save_runtime()

        @asynccontextmanager
        async def demo_lifespan(app):
            # No scheduler is started; the seeded progress is an illustrative state.
            yield

        main.app.router.lifespan_context = demo_lifespan

        @main.app.middleware("http")
        async def read_only(request, call_next):
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                return JSONResponse({"detail": "Documentation demo is read-only."}, status_code=403)
            return await call_next(request)

        print(f"Read-only demo: http://localhost:{port} (synthetic data; no scans or alerts)", flush=True)
        uvicorn.run(main.app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8093)
    run(parser.parse_args().port)
