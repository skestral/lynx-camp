from __future__ import annotations

from copy import deepcopy
from typing import Any

from .db import Store, utc_now
from .goingtocamp import connection_state
from .provider_registry import GTC_TENANTS, USEDIRECT_TENANTS
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
        "id": "snohomish-county-parks",
        "name": "Snohomish County Parks",
        "provider": "Snohomish County Parks",
        "category": "County and regional parks",
        "region": "WA",
        "areas": ["Puget Sound", "Everett and North Sound", "Snoqualmie and Cascades"],
        "counties": ["Snohomish"],
        "status": "ready",
        "source_type": "camava",
        "description": "Live campground discovery and exact-stay searches, including cabins and yurts. Reservations remain on the county website.",
        "official_url": "https://reservations.snocoparks.org/reservation/camping/",
        "queries": [],
    },
    {
        "id": "king-county-parks", "name": "King County Parks", "provider": "King County Parks",
        "category": "County and regional parks", "region": "WA", "counties": ["King"],
        "areas": ["Puget Sound", "Snoqualmie and Cascades"], "status": "ready", "source_type": "activenet",
        "description": "Live Tolt-MacDonald overnight searches: tent, RV, yurt, container, and group sites. Two to seven nights; manual booking.",
        "official_url": "https://kingcounty.gov/en/dept/dnrp/nature-recreation/parks-recreation/king-county-parks/rentals/camping",
        "queries": [],
    },
    {
        "id": "skagit-county-parks", "name": "Skagit County Parks", "provider": "Skagit County Parks",
        "category": "County and regional parks", "region": "WA", "counties": ["Skagit"],
        "areas": ["Everett and North Sound", "Snoqualmie and Cascades"], "status": "ready", "source_type": "cedar",
        "description": "Live Howard Miller Steelhead Park tent, RV, cabin, and Adirondack searches. Current-year bookings; manual checkout.",
        "official_url": "https://www.explore.skagitcounty.org/skagitcounty/discover/facility/e43b2789-e411-426f-9d75-b53a499c11ba",
        "queries": [],
    },
    {
        "id": "washington-state-parks",
        "name": "Washington State Parks",
        "provider": "Washington State Parks",
        "category": "Washington state",
        "region": "WA",
        "areas": ["Puget Sound", "Olympic Peninsula", "Mount Rainier", "Snoqualmie and Cascades", "Everett and North Sound"],
        "counties": ["Clallam", "Jefferson", "Kitsap", "Mason", "King", "Pierce", "Lewis", "Snohomish", "Island", "Skagit", "Thurston", "Grays Harbor"],
        "status": "ready",
        "source_type": "goingtocamp",
        "description": "Live Camping and Roofed availability, including cabins and yurts. Separate targets for each category; no browser or login required. Site names, capacity, and accommodation-specific filters are not available.",
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

# These providers are visible coverage gaps, not silent additions to scan queues.
for source_id, name, counties, areas, url, description in [
    ("clallam-county-parks", "Clallam County Parks", ["Clallam"], ["Olympic Peninsula"],
     "https://www.clallamcountywa.gov/297/Camping",
     "Salt Creek and Dungeness recreation areas. CampLife requires an account; server access not connected. Not scanned."),
    ("jefferson-county-parks", "Jefferson County Parks", ["Jefferson"], ["Olympic Peninsula", "Puget Sound"],
     "https://jeffersoncountywa.myrec.com/info/facilities/default.aspx",
     "Quilcene, Lake Leland, and Oak Bay campgrounds. First-come camping directory; no live nightly availability."),
    ("lewis-county-parks", "Lewis County Parks", ["Lewis"], ["Mount Rainier"],
     "https://lewiscountywa.gov/departments/parks-recreation/parks-venues/",
     "County park and fairground camping. Reservation connector pending; not scanned."),
]:
    SOURCE_DEFINITIONS.append({
        "id": source_id, "name": name, "provider": name, "category": "County and regional parks",
        "region": "WA", "areas": areas, "counties": counties,
        "status": "directory" if source_id == "jefferson-county-parks" else "research",
        "source_type": "reservation_directory", "official_url": url,
        "description": description, "queries": [],
    })


for tenant, config in GTC_TENANTS.items():
    if tenant == "wa":
        continue
    SOURCE_DEFINITIONS.append({
        "id": config["source"], "name": config["name"], "provider": config["name"],
        "category": "County and regional parks" if tenant == "tacoma" else "Canadian parks",
        "region": config["state"], "status": "experimental", "source_type": "goingtocamp", "tenant": tenant,
        "areas": ["Mount Rainier", "Puget Sound"] if tenant == "tacoma" else [],
        "counties": ["Pierce", "Lewis"] if tenant == "tacoma" else [], "queries": [],
        "official_url": f"https://{config['host']}/",
        "description": "Frontcountry Camping searches through the native API. Catalog verified; stay compatibility is under validation. Roofed, group, backcountry and day-use categories are not included.",
    })


for tenant, config in USEDIRECT_TENANTS.items():
    SOURCE_DEFINITIONS.append({
        "id": config["source"], "name": config["name"], "provider": config["name"],
        "category": "County and regional parks" if tenant == "metro" else "State parks",
        "region": config["state"], "status": "experimental", "source_type": "usedirect", "tenant": tenant,
        "official_url": config["booking"], "queries": [],
        "description": ("Oxbow campground and group camp only; not Oregon State Parks. " if tenant == "metro" else
                        "Conservative campground and lodging catalog; not every California facility is included. ")
                       + "Occupied-night calendar searches with booking-rule checks. Manual checkout on the provider website.",
    })


def list_source_definitions(store: Store) -> list[dict[str, Any]]:
    existing_targets = store.list_targets()
    sources = deepcopy(SOURCE_DEFINITIONS)
    for source in sources:
        source["query_count"] = len(source.get("queries") or [])
        source["discover_supported"] = _supports_discovery(source)
        source["import_supported"] = source["discover_supported"]
        source["imported_count"] = _imported_count_for_source(source, existing_targets)
        if source["source_type"] == "goingtocamp":
            source["connection"] = connection_state(store, source.get("tenant", "wa"))
        elif source["source_type"] == "usedirect":
            source["connection"] = connection_state(store, f"ud_{source['tenant']}")
        source.pop("queries", None)
    return sources


async def discover_source(store: Store, client: Any, source_id: str) -> dict[str, Any]:
    source = _get_source(source_id)
    if not _supports_discovery(source):
        raise ValueError(f"source {source_id} does not support live campground discovery yet")

    existing = {target["campground_id"] for target in store.list_targets()}
    discovered_by_id: dict[str, dict[str, Any]] = {}
    queries = source.get("queries") or []

    if source["source_type"] in {"camava", "activenet", "cedar", "goingtocamp", "usedirect"}:
        discovered_by_id = {target["campground_id"]: target for target in await client.discover_external(source_id)}
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
        "source": f"{source['provider']} campground search",
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
    if source.get("source_type") in {"goingtocamp", "usedirect"}:
        return source.get("status") in {"ready", "experimental"}
    return source.get("status") == "ready" and source.get("source_type") in {"recreation_search", "camava", "activenet", "cedar"}


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
    if source.get("source_type") == "usedirect":
        return sum(1 for target in targets if str(target.get("campground_id", "")).startswith(f"ud:{source['tenant']}:"))
    if source.get("source_type") == "goingtocamp":
        prefix = f"gtc:{source.get('tenant', 'wa')}:"
        return sum(1 for target in targets if str(target.get("campground_id", "")).startswith(prefix))
    if source.get("source_type") == "cedar":
        return sum(1 for target in targets if target.get("campground_id") == "cedar:skagit:hmsp")
    if source.get("source_type") == "activenet":
        return sum(1 for target in targets if target.get("campground_id") == "activenet:king:66")
    if source.get("source_type") == "camava":
        return sum(1 for target in targets if str(target.get("campground_id", "")).startswith("camava:snoco:"))
    queries = source.get("queries") or []
    if not queries:
        return 0

    imported_ids: set[str] = set()
    for target in targets:
        if ":" in str(target.get("campground_id", "")):
            continue
        suggestion_like = {
            "park_name": target.get("park_name"),
            "state_code": target.get("state_code"),
        }
        if any(_matches_query(suggestion_like, query) for query in queries):
            imported_ids.add(str(target.get("campground_id") or ""))
    return len([campground_id for campground_id in imported_ids if campground_id])
