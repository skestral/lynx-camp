from __future__ import annotations

from copy import deepcopy
from typing import Any

from .coordinates import CAMPGROUND_COORDINATES
from .db import Store, utc_now

SOURCE_SEARCH_PAGE_SIZE = 100
SOURCE_SEARCH_MAX_PAGES = 8


def _target(
    name: str,
    campground_id: str,
    park_name: str,
    state_code: str,
    timezone: str,
) -> dict[str, Any]:
    target = {
        "name": name,
        "campground_id": campground_id,
        "park_name": park_name,
        "state_code": state_code,
        "release_months": 6,
        "release_window_value": 6,
        "release_window_unit": "Months",
        "release_time": "07:00",
        "timezone": timezone,
        "poll_interval_minutes": 10,
    }
    coordinates = CAMPGROUND_COORDINATES.get(campground_id)
    if coordinates:
        target["latitude"], target["longitude"] = coordinates
    return target


OLYMPIC_TARGETS = [
    _target("Hoh Rainforest Campground", "247592", "Olympic National Park", "WA", "America/Los_Angeles"),
    _target("Sol Duc Hot Springs Resort Campground", "251906", "Olympic National Park", "WA", "America/Los_Angeles"),
    _target("Fairholme Campground", "259084", "Olympic National Park", "WA", "America/Los_Angeles"),
    _target("Staircase Campground", "247586", "Olympic National Park", "WA", "America/Los_Angeles"),
    _target("Mora Campground", "247591", "Olympic National Park", "WA", "America/Los_Angeles"),
    _target("Kalaloch", "232464", "Olympic National Park", "WA", "America/Los_Angeles"),
]

MOUNT_RAINIER_TARGETS = [
    _target("White River Campground", "259031", "Mount Rainier National Park", "WA", "America/Los_Angeles"),
    _target("Cougar Rock Campground", "232466", "Mount Rainier National Park", "WA", "America/Los_Angeles"),
    _target("Cougar Rock Group Campground", "232510", "Mount Rainier National Park", "WA", "America/Los_Angeles"),
    _target("Ohanapecosh Campground", "232465", "Mount Rainier National Park", "WA", "America/Los_Angeles"),
    _target("Ohanapecosh Group Campground", "232509", "Mount Rainier National Park", "WA", "America/Los_Angeles"),
]

CRATER_LAKE_TARGETS = [
    _target("Mazama Village Campground", "10337002", "Crater Lake National Park", "OR", "America/Los_Angeles"),
]

NORTH_CASCADES_TARGETS = [
    _target("Gorge Lake Campground", "10004932", "North Cascades National Park", "WA", "America/Los_Angeles"),
    _target("Newhalem Creek Campground", "234060", "North Cascades National Park", "WA", "America/Los_Angeles"),
    _target("Lower Goodell Group Campground", "234088", "North Cascades National Park", "WA", "America/Los_Angeles"),
    _target("Upper Goodell Group Campground", "234089", "North Cascades National Park", "WA", "America/Los_Angeles"),
    _target("Goodell Creek Campground", "246852", "North Cascades National Park", "WA", "America/Los_Angeles"),
    _target("Colonial Creek North Campground", "246855", "North Cascades National Park", "WA", "America/Los_Angeles"),
    _target("Colonial Creek South Campground", "255201", "North Cascades National Park", "WA", "America/Los_Angeles"),
    _target("Harlequin Campground", "10101324", "North Cascades National Park", "WA", "America/Los_Angeles"),
]

GLACIER_TARGETS = [
    _target("Avalanche Campground", "258796", "Glacier National Park", "MT", "America/Denver"),
    _target("Sprague Creek Campground", "258795", "Glacier National Park", "MT", "America/Denver"),
    _target("Many Glacier Campground", "251869", "Glacier National Park", "MT", "America/Denver"),
    _target("Fish Creek Campground", "232493", "Glacier National Park", "MT", "America/Denver"),
    _target("Rising Sun Campground", "10363618", "Glacier National Park", "MT", "America/Denver"),
    _target("Apgar Campground", "10171274", "Glacier National Park", "MT", "America/Denver"),
    _target("Apgar Group Sites", "234669", "Glacier National Park", "MT", "America/Denver"),
    _target("St. Mary Campground", "232492", "Glacier National Park", "MT", "America/Denver"),
    _target("Two Medicine Campground", "258799", "Glacier National Park", "MT", "America/Denver"),
]

YELLOWSTONE_TARGETS = [
    _target("Tower Fall Campground", "259308", "Yellowstone National Park", "WY", "America/Denver"),
    _target("Indian Creek Campground", "259304", "Yellowstone National Park", "WY", "America/Denver"),
    _target("Lewis Lake Campground", "259309", "Yellowstone National Park", "WY", "America/Denver"),
    _target("Mammoth Campground", "247571", "Yellowstone National Park", "WY", "America/Denver"),
    _target("Slough Creek Campground", "259310", "Yellowstone National Park", "WY", "America/Denver"),
]

GRAND_TETON_TARGETS = [
    _target("Jenny Lake Campground", "247664", "Grand Teton National Park", "WY", "America/Denver"),
    _target("Signal Mountain Campground", "247663", "Grand Teton National Park", "WY", "America/Denver"),
    _target("Colter Bay Marina End Ties", "10246274", "Grand Teton National Park", "WY", "America/Denver"),
    _target("Colter Bay RV Park", "258831", "Grand Teton National Park", "WY", "America/Denver"),
    _target("Colter Bay Campground", "258830", "Grand Teton National Park", "WY", "America/Denver"),
    _target("Colter Bay Tent Village", "10099575", "Grand Teton National Park", "WY", "America/Denver"),
    _target("Lizard Creek Campground", "247785", "Grand Teton National Park", "WY", "America/Denver"),
    _target("Gros Ventre Campground", "247661", "Grand Teton National Park", "WY", "America/Denver"),
    _target("Headwaters Campground at Flagg Ranch", "258832", "Grand Teton National Park", "WY", "America/Denver"),
]

PACIFIC_NORTHWEST_TARGETS = [
    *OLYMPIC_TARGETS,
    *MOUNT_RAINIER_TARGETS,
    *CRATER_LAKE_TARGETS,
    *NORTH_CASCADES_TARGETS,
    *GLACIER_TARGETS,
]


PRESET_PACKS: list[dict[str, Any]] = [
    {
        "id": "pacific-northwest-national-parks",
        "name": "PNW and Northern Rockies National Parks",
        "description": "All Recreation.gov campground facilities attached to Olympic, Mount Rainier, Crater Lake, North Cascades, and Glacier.",
        "region": "WA/OR/MT",
        "targets": PACIFIC_NORTHWEST_TARGETS,
    },
    {
        "id": "olympic-national-park",
        "name": "Olympic National Park",
        "description": "All Recreation.gov campground facilities attached to Olympic National Park.",
        "region": "WA",
        "targets": OLYMPIC_TARGETS,
    },
    {
        "id": "mount-rainier-national-park",
        "name": "Mount Rainier National Park",
        "description": "All Recreation.gov campground facilities attached to Mount Rainier National Park.",
        "region": "WA",
        "targets": MOUNT_RAINIER_TARGETS,
    },
    {
        "id": "crater-lake-national-park",
        "name": "Crater Lake National Park",
        "description": "All Recreation.gov campground facilities attached to Crater Lake National Park.",
        "region": "OR",
        "targets": CRATER_LAKE_TARGETS,
    },
    {
        "id": "north-cascades-national-park",
        "name": "North Cascades National Park",
        "description": "All Recreation.gov campground facilities attached to North Cascades National Park.",
        "region": "WA",
        "targets": NORTH_CASCADES_TARGETS,
    },
    {
        "id": "glacier-national-park",
        "name": "Glacier National Park",
        "description": "All Recreation.gov campground facilities attached to Glacier National Park.",
        "region": "MT",
        "targets": GLACIER_TARGETS,
    },
    {
        "id": "yellowstone-national-park",
        "name": "Yellowstone National Park",
        "description": "All Recreation.gov campground facilities attached to Yellowstone National Park.",
        "region": "WY",
        "targets": YELLOWSTONE_TARGETS,
    },
    {
        "id": "grand-teton-national-park",
        "name": "Grand Teton National Park",
        "description": "All Recreation.gov campground facilities attached to Grand Teton National Park.",
        "region": "WY",
        "targets": GRAND_TETON_TARGETS,
    },
    {
        "id": "california-national-parks",
        "name": "California National Parks",
        "description": "Yosemite, Sequoia/Kings Canyon, and Joshua Tree starter targets for high-demand trips.",
        "region": "CA",
        "targets": [
            _target("Upper Pines Campground", "232447", "Yosemite National Park", "CA", "America/Los_Angeles"),
            _target("North Pines Campground", "232449", "Yosemite National Park", "CA", "America/Los_Angeles"),
            _target("Lower Pines Campground", "232450", "Yosemite National Park", "CA", "America/Los_Angeles"),
            _target("Tuolumne Meadows Campground", "232448", "Yosemite National Park", "CA", "America/Los_Angeles"),
            _target(
                "Lodgepole Campground",
                "232461",
                "Sequoia & Kings Canyon National Parks",
                "CA",
                "America/Los_Angeles",
            ),
            _target("Jumbo Rocks Campground", "272300", "Joshua Tree National Park", "CA", "America/Los_Angeles"),
        ],
    },
]


def _normalize_name(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("&", " and ")
        .replace(".", "")
        .replace("-", " ")
    )


def _source_queries(pack: dict[str, Any]) -> list[dict[str, str]]:
    sources: dict[str, dict[str, str]] = {}
    for target in pack["targets"]:
        park_name = str(target.get("park_name") or "").strip()
        if not park_name:
            continue
        key = _normalize_name(park_name)
        if key not in sources:
            sources[key] = {
                "park_name": park_name,
                "state_code": target.get("state_code") or "",
                "timezone": target.get("timezone") or "America/Los_Angeles",
            }
    return list(sources.values())


def _matches_source_park(suggestion: dict[str, Any], source: dict[str, str]) -> bool:
    parent = _normalize_name(suggestion.get("park_name"))
    park = _normalize_name(source["park_name"])
    return bool(parent and park and parent == park)


def _source_target(suggestion: dict[str, Any], source: dict[str, str]) -> dict[str, Any]:
    target = _target(
        suggestion["name"],
        str(suggestion["campground_id"]),
        suggestion.get("park_name") or source["park_name"],
        suggestion.get("state_code") or source["state_code"],
        source["timezone"],
    )
    if suggestion.get("latitude") not in {None, ""}:
        target["latitude"] = suggestion.get("latitude")
    if suggestion.get("longitude") not in {None, ""}:
        target["longitude"] = suggestion.get("longitude")
    return target


async def _source_campgrounds(client: Any, source: dict[str, str]) -> list[dict[str, Any]]:
    if hasattr(client, "search_campgrounds"):
        campgrounds: list[dict[str, Any]] = []
        for page in range(SOURCE_SEARCH_MAX_PAGES):
            batch = await client.search_campgrounds(
                source["park_name"],
                size=SOURCE_SEARCH_PAGE_SIZE,
                start=page * SOURCE_SEARCH_PAGE_SIZE,
            )
            campgrounds.extend(batch)
            if len(batch) < SOURCE_SEARCH_PAGE_SIZE:
                break
        return campgrounds

    return await client.suggest_campgrounds(source["park_name"], size=50)


async def _verify_static_source_targets(
    client: Any,
    source: dict[str, str],
    static_targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not hasattr(client, "campground_by_id"):
        return []

    verified: list[dict[str, Any]] = []
    for target in static_targets:
        campground = await client.campground_by_id(str(target["campground_id"]))
        if campground and _matches_source_park(campground, source):
            verified.append(campground)
    return verified


def list_preset_packs(store: Store) -> list[dict[str, Any]]:
    existing = {target["campground_id"] for target in store.list_targets()}
    packs = deepcopy(PRESET_PACKS)
    for pack in packs:
        imported_count = 0
        for target in pack["targets"]:
            target["imported"] = target["campground_id"] in existing
            imported_count += 1 if target["imported"] else 0
        pack["target_count"] = len(pack["targets"])
        pack["imported_count"] = imported_count
    return packs


async def discover_preset_pack(store: Store, client: Any, pack_id: str) -> dict[str, Any]:
    pack = next((item for item in PRESET_PACKS if item["id"] == pack_id), None)
    if pack is None:
        raise ValueError(f"preset pack {pack_id} not found")

    static_by_id = {target["campground_id"]: deepcopy(target) for target in pack["targets"]}
    existing = {target["campground_id"] for target in store.list_targets()}
    discovered_by_id: dict[str, dict[str, Any]] = {}
    source_queries = _source_queries(pack)

    for source in source_queries:
        suggestions = await _source_campgrounds(client, source)
        matching_static_targets = [
            target
            for target in static_by_id.values()
            if _normalize_name(target.get("park_name")) == _normalize_name(source["park_name"])
        ]
        for suggestion in suggestions:
            campground_id = str(suggestion.get("campground_id") or "").strip()
            if not campground_id or not _matches_source_park(suggestion, source):
                continue
            discovered_by_id[campground_id] = _source_target(suggestion, source)
        missing_static_targets = [
            target for target in matching_static_targets if str(target["campground_id"]) not in discovered_by_id
        ]
        for suggestion in await _verify_static_source_targets(client, source, missing_static_targets):
            campground_id = str(suggestion.get("campground_id") or "").strip()
            if campground_id:
                discovered_by_id[campground_id] = _source_target(suggestion, source)

    for target in discovered_by_id.values():
        target["imported"] = target["campground_id"] in existing

    discovered_ids = set(discovered_by_id)
    static_ids = set(static_by_id)
    new_ids = sorted(discovered_ids - static_ids)
    missing_ids = sorted(static_ids - discovered_ids)
    unchanged_ids = sorted(discovered_ids & static_ids)

    return {
        "pack_id": pack["id"],
        "pack_name": pack["name"],
        "checked_at": utc_now(),
        "source": "Recreation.gov campground search",
        "source_queries": [source["park_name"] for source in source_queries],
        "static_count": len(static_ids),
        "discovered_count": len(discovered_ids),
        "imported_count": sum(1 for target in discovered_by_id.values() if target.get("imported")),
        "new_count": len(new_ids),
        "missing_count": len(missing_ids),
        "unchanged_count": len(unchanged_ids),
        "new_targets": [discovered_by_id[campground_id] for campground_id in new_ids],
        "missing_static_targets": [static_by_id[campground_id] for campground_id in missing_ids],
        "targets": sorted(discovered_by_id.values(), key=lambda target: (target.get("park_name") or "", target["name"])),
    }


async def import_discovered_preset_pack(
    store: Store,
    client: Any,
    pack_id: str,
    min_poll_interval_minutes: int,
) -> dict[str, Any]:
    discovery = await discover_preset_pack(store, client, pack_id)
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
        "pack_id": discovery["pack_id"],
        "source": discovery["source"],
        "checked_at": discovery["checked_at"],
        "imported_count": len(imported),
        "updated_count": len(updated),
        "target_count": len(discovery["targets"]),
        "new_count": discovery["new_count"],
        "missing_count": discovery["missing_count"],
        "targets": imported + updated,
        "discovery": discovery,
    }


def import_preset_pack(store: Store, pack_id: str, min_poll_interval_minutes: int) -> dict[str, Any]:
    pack = next((item for item in PRESET_PACKS if item["id"] == pack_id), None)
    if pack is None:
        raise ValueError(f"preset pack {pack_id} not found")

    before = {target["campground_id"] for target in store.list_targets()}
    imported = []
    updated = []
    for target in pack["targets"]:
        saved = store.create_target(target, min_poll_interval_minutes)
        if target["campground_id"] in before:
            updated.append(saved)
        else:
            imported.append(saved)

    return {
        "pack_id": pack["id"],
        "imported_count": len(imported),
        "updated_count": len(updated),
        "target_count": len(pack["targets"]),
        "targets": imported + updated,
    }
