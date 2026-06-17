from __future__ import annotations

from copy import deepcopy
from typing import Any

from .db import Store, utc_now
from .presets import SOURCE_SEARCH_MAX_PAGES, SOURCE_SEARCH_PAGE_SIZE, _normalize_name, _target

SourceQuery = dict[str, Any]
SourceDefinition = dict[str, Any]


SOURCE_DEFINITIONS: list[SourceDefinition] = [
    {
        "id": "pnw-national-parks-live",
        "name": "PNW National Parks",
        "provider": "Recreation.gov",
        "category": "National parks",
        "region": "WA/OR/MT",
        "status": "ready",
        "source_type": "recreation_search",
        "description": "Live Recreation.gov campground search for the PNW and Northern Rockies national park set.",
        "official_url": "https://www.recreation.gov/",
        "queries": [
            {"query": "Olympic National Park", "parent_name": "Olympic National Park", "state_code": "WA", "timezone": "America/Los_Angeles", "match": "parent_exact"},
            {"query": "Mount Rainier National Park", "parent_name": "Mount Rainier National Park", "state_code": "WA", "timezone": "America/Los_Angeles", "match": "parent_exact"},
            {"query": "Crater Lake National Park", "parent_name": "Crater Lake National Park", "state_code": "OR", "timezone": "America/Los_Angeles", "match": "parent_exact"},
            {"query": "North Cascades National Park", "parent_name": "North Cascades National Park", "state_code": "WA", "timezone": "America/Los_Angeles", "match": "parent_exact"},
            {"query": "Glacier National Park", "parent_name": "Glacier National Park", "state_code": "MT", "timezone": "America/Denver", "match": "parent_exact"},
            {"query": "Yellowstone National Park", "parent_name": "Yellowstone National Park", "state_code": "WY", "timezone": "America/Denver", "match": "parent_exact"},
            {"query": "Grand Teton National Park", "parent_name": "Grand Teton National Park", "state_code": "WY", "timezone": "America/Denver", "match": "parent_exact"},
        ],
    },
    {
        "id": "washington-national-forests-live",
        "name": "Washington National Forests",
        "provider": "Recreation.gov",
        "category": "National forests",
        "region": "WA",
        "status": "ready",
        "source_type": "recreation_search",
        "description": "Forest-level Recreation.gov campground discovery for Washington trips beyond national parks.",
        "official_url": "https://www.recreation.gov/",
        "queries": [
            {"query": "Olympic National Forest", "parent_name": "Olympic National Forest", "state_code": "WA", "timezone": "America/Los_Angeles", "match": "parent_exact"},
            {"query": "Mount Baker Snoqualmie National Forest", "parent_name": "Mt. Baker-Snoqualmie National Forest", "state_code": "WA", "timezone": "America/Los_Angeles", "match": "parent_exact"},
            {"query": "Okanogan-Wenatchee National Forest", "parent_name": "Okanogan-Wenatchee National Forest", "state_code": "WA", "timezone": "America/Los_Angeles", "match": "parent_exact"},
            {"query": "Gifford Pinchot National Forest", "parent_name": "Gifford Pinchot National Forest", "state_code": "WA", "timezone": "America/Los_Angeles", "match": "parent_exact"},
            {"query": "Colville National Forest", "parent_name": "Colville National Forest", "state_code": "WA", "timezone": "America/Los_Angeles", "match": "parent_exact"},
        ],
    },
    {
        "id": "washington-recreation-gov-region",
        "name": "Washington Recreation.gov Region",
        "provider": "Recreation.gov",
        "category": "Regions",
        "region": "WA",
        "status": "ready",
        "source_type": "recreation_search",
        "description": "A state-filtered Recreation.gov search starter for federal campgrounds in Washington.",
        "official_url": "https://www.recreation.gov/",
        "queries": [
            {"query": "Washington", "state_code": "WA", "timezone": "America/Los_Angeles", "match": "state"},
        ],
    },
    {
        "id": "washington-state-parks",
        "name": "Washington State Parks",
        "provider": "Washington State Parks",
        "category": "Washington state",
        "region": "WA",
        "status": "research",
        "source_type": "reservation_directory",
        "description": "Official reservation links and reservable-park research. Availability scanning is not enabled until the reservation system is reviewed safely.",
        "official_url": "https://parks.wa.gov/passes-permits/reservations/reservation-parks",
        "queries": [],
    },
    {
        "id": "washington-dnr-campgrounds",
        "name": "Washington DNR Campgrounds",
        "provider": "Washington DNR",
        "category": "Washington state",
        "region": "WA",
        "status": "directory",
        "source_type": "gis_directory",
        "description": "WA DNR open GIS campground records can seed maps and directories, but they are not Recreation.gov availability targets.",
        "official_url": "https://data-wadnr.opendata.arcgis.com/datasets/wadnr%3A%3Adnr-campgrounds/explore",
        "queries": [],
    },
]


def list_source_definitions(store: Store) -> list[dict[str, Any]]:
    existing_targets = store.list_targets()
    sources = deepcopy(SOURCE_DEFINITIONS)
    for source in sources:
        source["query_count"] = len(source.get("queries") or [])
        source["discover_supported"] = source.get("status") == "ready" and source.get("source_type") == "recreation_search"
        source["import_supported"] = source["discover_supported"]
        source["imported_count"] = _imported_count_for_source(source, existing_targets)
        source.pop("queries", None)
    return sources


async def discover_source(store: Store, client: Any, source_id: str) -> dict[str, Any]:
    source = _get_source(source_id)
    if not _supports_discovery(source):
        raise ValueError(f"source {source_id} does not support live Recreation.gov discovery yet")

    existing = {target["campground_id"] for target in store.list_targets()}
    discovered_by_id: dict[str, dict[str, Any]] = {}
    queries = source.get("queries") or []

    for query in queries:
        for suggestion in await _source_campgrounds(client, query):
            campground_id = str(suggestion.get("campground_id") or "").strip()
            if not campground_id or not _matches_query(suggestion, query):
                continue
            discovered_by_id[campground_id] = _source_target(suggestion, source, query)

    for target in discovered_by_id.values():
        target["imported"] = target["campground_id"] in existing

    targets = sorted(discovered_by_id.values(), key=lambda target: (target.get("park_name") or "", target["name"]))
    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "provider": source["provider"],
        "category": source["category"],
        "region": source["region"],
        "status": source["status"],
        "source": "Recreation.gov campground search",
        "checked_at": utc_now(),
        "source_queries": [query["query"] for query in queries],
        "discovered_count": len(targets),
        "imported_count": sum(1 for target in targets if target.get("imported")),
        "new_count": sum(1 for target in targets if not target.get("imported")),
        "targets": targets,
    }


async def import_source(
    store: Store,
    client: Any,
    source_id: str,
    min_poll_interval_minutes: int,
) -> dict[str, Any]:
    discovery = await discover_source(store, client, source_id)
    before = {target["campground_id"] for target in store.list_targets()}
    imported = []
    updated = []

    for target in discovery["targets"]:
        saved = store.create_target(target, min_poll_interval_minutes)
        if target["campground_id"] in before:
            updated.append(saved)
        else:
            imported.append(saved)

    return {
        "source_id": discovery["source_id"],
        "source_name": discovery["source_name"],
        "source": discovery["source"],
        "checked_at": discovery["checked_at"],
        "imported_count": len(imported),
        "updated_count": len(updated),
        "target_count": len(discovery["targets"]),
        "new_count": discovery["new_count"],
        "targets": imported + updated,
        "discovery": discovery,
    }


def _get_source(source_id: str) -> SourceDefinition:
    source = next((item for item in SOURCE_DEFINITIONS if item["id"] == source_id), None)
    if source is None:
        raise ValueError(f"source {source_id} not found")
    return source


def _supports_discovery(source: SourceDefinition) -> bool:
    return source.get("status") == "ready" and source.get("source_type") == "recreation_search"


async def _source_campgrounds(client: Any, query: SourceQuery) -> list[dict[str, Any]]:
    if hasattr(client, "search_campgrounds"):
        campgrounds: list[dict[str, Any]] = []
        for page in range(SOURCE_SEARCH_MAX_PAGES):
            batch = await client.search_campgrounds(
                query["query"],
                size=SOURCE_SEARCH_PAGE_SIZE,
                start=page * SOURCE_SEARCH_PAGE_SIZE,
            )
            campgrounds.extend(batch)
            if len(batch) < SOURCE_SEARCH_PAGE_SIZE:
                break
        return campgrounds

    return await client.suggest_campgrounds(query["query"], size=50)


def _matches_query(suggestion: dict[str, Any], query: SourceQuery) -> bool:
    state_code = str(query.get("state_code") or "").upper()
    if state_code and str(suggestion.get("state_code") or "").upper() != state_code:
        return False

    match_mode = query.get("match") or "parent_exact"
    if match_mode == "state":
        return bool(state_code)

    parent_name = query.get("parent_name") or query.get("query")
    if match_mode == "parent_exact":
        return _normalize_name(suggestion.get("park_name")) == _normalize_name(parent_name)

    if match_mode == "parent_contains":
        parent = _normalize_name(suggestion.get("park_name"))
        needle = _normalize_name(parent_name)
        return bool(parent and needle and needle in parent)

    return True


def _source_target(suggestion: dict[str, Any], source: SourceDefinition, query: SourceQuery) -> dict[str, Any]:
    target = _target(
        suggestion["name"],
        str(suggestion["campground_id"]),
        suggestion.get("park_name") or query.get("parent_name") or source["name"],
        suggestion.get("state_code") or query.get("state_code") or source.get("region") or "",
        query.get("timezone") or "America/Los_Angeles",
    )
    if suggestion.get("latitude") not in {None, ""}:
        target["latitude"] = suggestion.get("latitude")
    if suggestion.get("longitude") not in {None, ""}:
        target["longitude"] = suggestion.get("longitude")
    return target


def _imported_count_for_source(source: SourceDefinition, targets: list[dict[str, Any]]) -> int:
    queries = source.get("queries") or []
    if not queries:
        return 0

    imported_ids: set[str] = set()
    for target in targets:
        suggestion_like = {
            "park_name": target.get("park_name"),
            "state_code": target.get("state_code"),
        }
        if any(_matches_query(suggestion_like, query) for query in queries):
            imported_ids.add(str(target.get("campground_id") or ""))
    return len([campground_id for campground_id in imported_ids if campground_id])
