from __future__ import annotations

import asyncio

from backend.app.db import Store
from backend.app.presets import discover_preset_pack, import_discovered_preset_pack, import_preset_pack, list_preset_packs


class FakeRecreationClient:
    async def search_campgrounds(self, query: str, size: int = 100, start: int = 0):
        assert size == 100
        if query == "Olympic National Park" and start == 0:
            return [
                {
                    "name": "Kalaloch",
                    "campground_id": "232464",
                    "park_name": "Olympic National Park",
                    "state_code": "WA",
                    "latitude": "47.613",
                    "longitude": "-124.374",
                },
                {
                    "name": "New Olympic Source Campground",
                    "campground_id": "999001",
                    "park_name": "Olympic National Park",
                    "state_code": "WA",
                    "latitude": "47.9",
                    "longitude": "-123.9",
                },
                {
                    "name": "Wrong Parent Campground",
                    "campground_id": "999002",
                    "park_name": "Not Olympic National Park",
                    "state_code": "WA",
                },
            ]
        return []

    async def campground_by_id(self, campground_id: str):
        if campground_id == "247591":
            return {
                "name": "Mora Campground",
                "campground_id": "247591",
                "park_name": "Olympic National Park",
                "state_code": "WA",
                "latitude": "47.921",
                "longitude": "-124.607",
            }
        return None

    async def suggest_campgrounds(self, query: str, size: int = 10):
        assert size == 50
        if query == "Olympic National Park":
            return [
                {
                    "name": "Kalaloch",
                    "campground_id": "232464",
                    "park_name": "Olympic National Park",
                    "state_code": "WA",
                    "latitude": "47.613",
                    "longitude": "-124.374",
                },
                {
                    "name": "New Olympic Source Campground",
                    "campground_id": "999001",
                    "park_name": "Olympic National Park",
                    "state_code": "WA",
                    "latitude": "47.9",
                    "longitude": "-123.9",
                },
                {
                    "name": "Wrong Parent Campground",
                    "campground_id": "999002",
                    "park_name": "Not Olympic National Park",
                    "state_code": "WA",
                },
            ]
        return []


def test_preset_import_adds_targets_and_marks_imported(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    result = import_preset_pack(store, "pacific-northwest-national-parks", min_poll_interval_minutes=10)
    packs = list_preset_packs(store)
    imported_pack = next(pack for pack in packs if pack["id"] == "pacific-northwest-national-parks")

    assert result["imported_count"] == 29
    assert result["updated_count"] == 0
    assert imported_pack["imported_count"] == imported_pack["target_count"]
    assert {target["campground_id"] for target in store.list_targets()} >= {"232464", "232466", "10337002", "258799"}


def test_requested_national_park_packs_are_available(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    packs = {pack["id"]: pack for pack in list_preset_packs(store)}

    assert packs["olympic-national-park"]["target_count"] == 6
    assert packs["mount-rainier-national-park"]["target_count"] == 5
    assert packs["crater-lake-national-park"]["target_count"] == 1
    assert packs["north-cascades-national-park"]["target_count"] == 8
    assert packs["glacier-national-park"]["target_count"] == 9
    assert packs["yellowstone-national-park"]["target_count"] == 5
    assert packs["grand-teton-national-park"]["target_count"] == 9


def test_preset_reimport_updates_existing_targets(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    import_preset_pack(store, "california-national-parks", min_poll_interval_minutes=10)
    result = import_preset_pack(store, "california-national-parks", min_poll_interval_minutes=10)

    assert result["imported_count"] == 0
    assert result["updated_count"] == result["target_count"]


def test_discover_preset_pack_compares_static_and_source_targets(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    store.create_target(
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

    result = asyncio.run(discover_preset_pack(store, FakeRecreationClient(), "olympic-national-park"))

    assert result["source"] == "Recreation.gov campground search"
    assert result["static_count"] == 6
    assert result["discovered_count"] == 3
    assert result["new_count"] == 1
    assert result["missing_count"] == 4
    assert result["imported_count"] == 1
    assert [target["campground_id"] for target in result["new_targets"]] == ["999001"]
    assert {target["campground_id"] for target in result["targets"]} == {"232464", "247591", "999001"}


def test_import_discovered_preset_pack_imports_live_source_targets(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    result = asyncio.run(
        import_discovered_preset_pack(
            store,
            FakeRecreationClient(),
            "olympic-national-park",
            min_poll_interval_minutes=10,
        )
    )

    assert result["imported_count"] == 3
    assert result["updated_count"] == 0
    assert result["target_count"] == 3
    targets = {target["campground_id"]: target for target in store.list_targets()}
    assert set(targets) == {"232464", "247591", "999001"}
    assert targets["999001"]["park_name"] == "Olympic National Park"
