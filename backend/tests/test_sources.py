from __future__ import annotations

import asyncio

from backend.app.db import Store
from backend.app.sources import discover_source, import_source, list_source_definitions


class FakeSourceClient:
    async def search_campgrounds(self, query: str, size: int = 100, start: int = 0):
        assert size == 100
        if start > 0:
            return []
        if query == "Olympic National Forest":
            return [
                {
                    "name": "Coho Campground",
                    "campground_id": "100001",
                    "park_name": "Olympic National Forest",
                    "state_code": "WA",
                    "latitude": "47.45",
                    "longitude": "-123.22",
                },
                {
                    "name": "Wrong Forest Campground",
                    "campground_id": "100002",
                    "park_name": "Mount Hood National Forest",
                    "state_code": "OR",
                },
            ]
        if query == "Washington":
            return [
                {
                    "name": "Federal WA Campground",
                    "campground_id": "200001",
                    "park_name": "Example Federal Area",
                    "state_code": "WA",
                },
                {
                    "name": "Federal OR Campground",
                    "campground_id": "200002",
                    "park_name": "Example Federal Area",
                    "state_code": "OR",
                },
            ]
        return []


def test_source_catalog_lists_ready_and_research_sources(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    sources = {source["id"]: source for source in list_source_definitions(store)}

    assert sources["pnw-national-parks-live"]["discover_supported"] is True
    assert sources["washington-national-forests-live"]["category"] == "National forests"
    assert sources["washington-recreation-gov-region"]["region"] == "WA"
    assert sources["washington-state-parks"]["status"] == "research"
    assert sources["washington-state-parks"]["discover_supported"] is False
    assert sources["washington-dnr-campgrounds"]["status"] == "directory"


def test_discover_source_filters_by_parent_source(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    result = asyncio.run(discover_source(store, FakeSourceClient(), "washington-national-forests-live"))

    assert result["source_name"] == "Washington National Forests"
    assert result["provider"] == "Recreation.gov"
    assert result["discovered_count"] == 1
    assert result["new_count"] == 1
    assert result["targets"][0]["name"] == "Coho Campground"
    assert result["targets"][0]["park_name"] == "Olympic National Forest"


def test_discover_source_filters_by_state_region(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    result = asyncio.run(discover_source(store, FakeSourceClient(), "washington-recreation-gov-region"))

    assert result["source_name"] == "Washington Recreation.gov Region"
    assert result["discovered_count"] == 1
    assert result["targets"][0]["campground_id"] == "200001"


def test_import_source_creates_targets_and_updates_catalog_count(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    result = asyncio.run(
        import_source(
            store,
            FakeSourceClient(),
            "washington-national-forests-live",
            min_poll_interval_minutes=10,
        )
    )

    assert result["imported_count"] == 1
    assert result["updated_count"] == 0
    sources = {source["id"]: source for source in list_source_definitions(store)}
    assert sources["washington-national-forests-live"]["imported_count"] == 1
    targets = store.list_targets()
    assert targets[0]["campground_id"] == "100001"
