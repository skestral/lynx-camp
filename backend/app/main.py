from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .cart_assist import CartAssistant
from .db import Store
from .notifications import Notifier
from .presets import discover_preset_pack, import_discovered_preset_pack, import_preset_pack, list_preset_packs
from .recreation import RateLimitError, RecreationClient
from .scan_config import reset_scan_config, scan_config, update_scan_config
from .scanner import Scanner, generate_trip_windows, release_hints
from .schemas import (
    CartAssistConfigUpdate,
    CartAttemptStatusUpdate,
    ConfigBackup,
    NotificationConfigUpdate,
    ResultStatusUpdate,
    ScanConfigUpdate,
    TargetCreate,
    TargetUpdate,
    WatchCreate,
    WatchUpdate,
)
from .settings import settings
from .sources import discover_source, import_source, list_source_definitions


store = Store(settings.database_path)
client = RecreationClient()
notifier = Notifier(settings, store)
cart_assistant = CartAssistant(store, settings)
scanner = Scanner(
    store,
    client,
    notifier,
    settings.min_poll_interval_minutes,
    cart_assistant,
    settings.release_scan_before_minutes,
    settings.release_scan_after_minutes,
    settings.release_scan_interval_minutes,
    settings.availability_cache_minutes,
    settings.api_request_delay_seconds,
    settings.rate_limit_backoff_minutes,
    settings.max_notification_results,
)


def apply_scan_config() -> dict:
    config = scan_config(store, settings)
    scanner.configure_scan_controls(**config["values"])
    return config


def current_min_poll_interval_minutes() -> int:
    return scanner.min_poll_interval_minutes


async def scan_loop() -> None:
    while True:
        await scanner.scan_due_watches()
        await asyncio.sleep(settings.scan_loop_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init()
    apply_scan_config()
    store.cancel_running_scan_runs("Server restarted before this scan finished.", status="interrupted")
    task = asyncio.create_task(scan_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Camp Finder", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "database": str(settings.database_path)}


@app.get("/api/search")
async def search_campgrounds(q: str = Query(min_length=2)) -> list[dict]:
    return await client.suggest_campgrounds(q)


@app.get("/api/targets")
def list_targets() -> list[dict]:
    return store.list_targets()


@app.post("/api/targets")
def create_target(payload: TargetCreate) -> dict:
    return store.create_target(payload.model_dump(), current_min_poll_interval_minutes())


@app.patch("/api/targets/{target_id}")
def update_target(target_id: int, payload: TargetUpdate) -> dict:
    target = store.update_target(target_id, payload.model_dump(exclude_unset=True), current_min_poll_interval_minutes())
    if target is None:
        raise HTTPException(status_code=404, detail=f"target {target_id} not found")
    return target


@app.post("/api/targets/{target_id}/detect-release-window")
async def detect_target_release_window(target_id: int) -> dict:
    target = store.get_target(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail=f"target {target_id} not found")
    detected = await client.detect_release_window(target["campground_id"])
    if detected is None:
        raise HTTPException(status_code=404, detail="No reservation window data found for this target")
    updated = store.update_target(
        target_id,
        {
            "release_window_value": detected["release_window_value"],
            "release_window_unit": detected["release_window_unit"],
        },
        current_min_poll_interval_minutes(),
    )
    return {"target": updated, "detected": detected}


@app.get("/api/targets/{target_id}/release-window-profiles")
async def target_release_window_profiles(target_id: int) -> dict:
    target = store.get_target(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail=f"target {target_id} not found")
    return await client.release_window_profiles(target["campground_id"])


@app.get("/api/campgrounds/{campground_id}/details")
async def campground_details(campground_id: str) -> dict:
    saved_target = store.get_target_by_campground_id(campground_id)
    try:
        details = await client.campground_details(campground_id)
    except RateLimitError as exc:
        if saved_target:
            return _saved_target_campground_details(
                saved_target,
                "Recreation.gov rate-limited the campground details request, so Camp Finder is showing the saved target record.",
            )
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if details is None:
        if saved_target:
            return _saved_target_campground_details(saved_target)
        raise HTTPException(status_code=404, detail=f"campground {campground_id} not found")
    if saved_target:
        details["name"] = saved_target.get("name") or details["name"]
        details["park_name"] = saved_target.get("park_name") or ""
        details["state_code"] = saved_target.get("state_code") or ""
    return details


def _saved_target_campground_details(target: dict, description: str | None = None) -> dict:
    campground_id = str(target.get("campground_id") or "")
    detail_url = target.get("booking_url") or f"https://www.recreation.gov/camping/campgrounds/{campground_id}"
    return {
        "campground_id": campground_id,
        "name": target.get("name") or "Campground",
        "park_name": target.get("park_name") or "",
        "state_code": target.get("state_code") or "",
        "description": description
        or "Recreation.gov does not currently return a campground details record for this saved target.",
        "overview": "",
        "facilities": "",
        "natural_features": "",
        "recreation": "",
        "directions": "",
        "phone": "",
        "address": "",
        "latitude": target.get("latitude"),
        "longitude": target.get("longitude"),
        "timezone": target.get("timezone") or "",
        "amenities": [],
        "activities": [],
        "notices": [],
        "links": [],
        "image_url": "",
        "detail_url": detail_url,
        "source": "Saved Camp Finder target",
    }


@app.delete("/api/targets/{target_id}")
def delete_target(target_id: int) -> dict:
    deleted = store.delete_target(target_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"target {target_id} not found")
    return {"deleted": True}


@app.get("/api/presets")
def list_presets() -> list[dict]:
    return list_preset_packs(store)


@app.post("/api/presets/{pack_id}/import")
def import_preset(pack_id: str) -> dict:
    try:
        return import_preset_pack(store, pack_id, current_min_poll_interval_minutes())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/presets/{pack_id}/discover")
async def discover_preset(pack_id: str) -> dict:
    try:
        return await discover_preset_pack(store, client, pack_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/presets/{pack_id}/import-discovered")
async def import_discovered_preset(pack_id: str) -> dict:
    try:
        return await import_discovered_preset_pack(store, client, pack_id, current_min_poll_interval_minutes())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/sources")
def list_sources() -> list[dict]:
    return list_source_definitions(store)


@app.post("/api/sources/{source_id}/discover")
async def discover_source_definition(source_id: str) -> dict:
    try:
        return await discover_source(store, client, source_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sources/{source_id}/import")
async def import_source_definition(source_id: str) -> dict:
    try:
        return await import_source(store, client, source_id, current_min_poll_interval_minutes())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/config/export")
def export_config(include_secrets: bool = Query(default=False)) -> dict:
    return store.export_config(include_secrets=include_secrets)


@app.post("/api/config/import")
def import_config(payload: ConfigBackup) -> dict:
    try:
        return store.import_config(payload.model_dump(mode="json"), current_min_poll_interval_minutes())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/watches")
def list_watches() -> list[dict]:
    watches = store.list_watches()
    for watch in watches:
        trips = generate_trip_windows(watch)
        watch["candidate_count"] = len([trip for trip in trips if trip.arrival_date >= date.today()])
        watch["release_hints"] = release_hints(watch)
    return watches


@app.post("/api/watches")
def create_watch(payload: WatchCreate) -> dict:
    watch = store.create_watch(payload.model_dump(mode="json"))
    watch["candidate_count"] = len(generate_trip_windows(watch))
    watch["release_hints"] = release_hints(watch)
    return watch


@app.post("/api/watches/{watch_id}/scan")
async def run_scan(watch_id: int) -> dict:
    try:
        return await scanner.scan_watch(watch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/watches/{watch_id}")
def update_watch(watch_id: int, payload: WatchUpdate) -> dict:
    try:
        watch = store.update_watch(watch_id, payload.model_dump(exclude_unset=True, mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if watch is None:
        raise HTTPException(status_code=404, detail=f"watch {watch_id} not found")
    trips = generate_trip_windows(watch)
    watch["candidate_count"] = len([trip for trip in trips if trip.arrival_date >= date.today()])
    watch["release_hints"] = release_hints(watch)
    return watch


@app.post("/api/scans/run-all")
async def run_all_scans() -> dict:
    return await scanner.scan_all_watches()


@app.get("/api/scans")
def list_scan_runs(limit: int = Query(default=25, ge=1, le=100)) -> list[dict]:
    return store.list_scan_runs(limit)


@app.get("/api/scans/events")
def list_scan_events(limit: int = Query(default=100, ge=1, le=300)) -> list[dict]:
    return store.list_scan_events(limit)


@app.post("/api/scans/cancel")
def cancel_scan() -> dict:
    return scanner.cancel_current_scan()


@app.delete("/api/watches/{watch_id}")
def delete_watch(watch_id: int) -> dict:
    deleted = store.delete_watch(watch_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"watch {watch_id} not found")
    return {"deleted": True}


@app.get("/api/results")
def list_results(limit: int = Query(default=2000, ge=1, le=2000)) -> list[dict]:
    return store.list_results(limit)


@app.get("/api/results/summary")
def result_summary() -> dict:
    return store.result_summary()


@app.post("/api/results/clear")
def clear_results() -> dict:
    return {"cleared_count": store.clear_active_results()}


@app.patch("/api/results/{result_id}")
def update_result_status(result_id: int, payload: ResultStatusUpdate) -> dict:
    result = store.update_result_status(result_id, payload.status)
    if result is None:
        raise HTTPException(status_code=404, detail=f"result {result_id} not found")
    return result


@app.get("/api/notifications")
def list_notifications(limit: int = Query(default=25, ge=1, le=100)) -> list[dict]:
    return store.list_notifications(limit)


@app.get("/api/notifications/status")
def notification_status() -> dict:
    return notifier.status()


@app.get("/api/notifications/config")
def notification_config() -> dict:
    return notifier.notification_config()


@app.patch("/api/notifications/config")
def update_notification_config(payload: NotificationConfigUpdate) -> dict:
    return notifier.update_config(payload.model_dump(exclude_unset=True))


@app.post("/api/notifications/home-assistant/clear")
def clear_home_assistant_webhook() -> dict:
    return notifier.clear_home_assistant_webhook()


@app.post("/api/notifications/secrets/clear")
def clear_notification_secrets() -> dict:
    return notifier.clear_notification_secrets()


@app.post("/api/notifications/test")
async def test_notifications() -> dict:
    return await notifier.send_test()


@app.get("/api/scan-config")
def get_scan_config() -> dict:
    return scan_config(store, settings)


@app.patch("/api/scan-config")
def save_scan_config(payload: ScanConfigUpdate) -> dict:
    config = update_scan_config(store, settings, payload.model_dump(exclude_unset=True))
    scanner.configure_scan_controls(**config["values"])
    return config


@app.post("/api/scan-config/reset")
def restore_scan_config_defaults() -> dict:
    config = reset_scan_config(store, settings)
    scanner.configure_scan_controls(**config["values"])
    return config


@app.get("/api/cart-assist/status")
def cart_assist_status() -> dict:
    return cart_assistant.status()


@app.patch("/api/cart-assist/config")
def update_cart_assist_config(payload: CartAssistConfigUpdate) -> dict:
    return cart_assistant.update_config(payload.model_dump(exclude_unset=True))


@app.post("/api/cart-assist/credentials/clear")
def clear_cart_assist_credentials() -> dict:
    return cart_assistant.clear_credentials()


@app.get("/api/cart-assist/attempts")
def list_cart_attempts(limit: int = Query(default=25, ge=1, le=100)) -> list[dict]:
    return store.list_cart_attempts(limit)


@app.patch("/api/cart-assist/attempts/{attempt_id}")
def update_cart_attempt(attempt_id: int, payload: CartAttemptStatusUpdate) -> dict:
    try:
        attempt = store.update_cart_attempt_status(attempt_id, payload.status, payload.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if attempt is None:
        raise HTTPException(status_code=404, detail=f"cart attempt {attempt_id} not found")
    return attempt


if settings.static_dir.exists():
    app.mount("/assets", StaticFiles(directory=settings.static_dir / "assets"), name="assets")


@app.get("/{path:path}")
def serve_frontend(path: str):
    index = settings.static_dir / "index.html"
    requested = settings.static_dir / path
    if requested.exists() and requested.is_file():
        return FileResponse(requested)
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {
            "message": "Camp Finder API is running. Build the frontend with `npm run build` in frontend/ to serve the UI."
        }
    )
