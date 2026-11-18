"""Build a reviewable Canadian location reference from official public datasets.

Run from the repo root. Downloads are cached under ignored output/, never appdata.
No availability, account, booking, or notification endpoints are used.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import re
import sys
import unicodedata

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.goingtocamp import GoingToCampClient

BC_API = "https://bcparks.api.gov.bc.ca/api/protected-areas"
PC_API = "https://services2.arcgis.com/wCOMu5IS7YdSyPNx/ArcGIS/rest/services/Accommodation_Hebergement_APCA_OpenOuvert/FeatureServer/0/query"
PC_PARKS_API = "https://services2.arcgis.com/wCOMu5IS7YdSyPNx/ArcGIS/rest/services/PCA_Boundaries_NP/FeatureServer/8/query"


def name_key(value):
    value = unicodedata.normalize("NFKD", str(value)).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"\b(provincial|national|park|campground|campsite|camping)\b", " ", value)
    value = re.sub(r"\bvillage ii\b", "village 2", value)
    value = re.sub(r"\bvillage i\b", "village 1", value)
    value = re.sub(r"\bchignecto section [a-d]\b", "chignecto", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def canadian_point(lat, lon):
    return (type(lat) in (float, int) and type(lon) in (float, int)
            and 41 <= lat <= 84 and -142 <= lon <= -50)


def representative_point(points):
    # A dispersed backcountry area has no single campground location.
    if not points or max(p[0] for p in points) - min(p[0] for p in points) > 0.25 or max(p[1] for p in points) - min(p[1] for p in points) > 0.4:
        return None
    lat = sum(p[0] for p in points) / len(points)
    lon = sum(p[1] for p in points) / len(points)
    weight = math.cos(math.radians(lat)) ** 2
    return min(points, key=lambda p: (p[0] - lat) ** 2 + (p[1] - lon) ** 2 * weight)


def resolve(catalogs, bc, pc, parks):
    park_bounds = {}
    for park in parks:
        points = [p for ring in park.get("geometry", {}).get("rings", []) for p in ring]
        if points:
            park_name = re.sub(r"\s+NP(?:R)?$", "", park["attributes"]["Park_Name_"])
            park_bounds[name_key(park_name)] = (
                min(p[1] for p in points), max(p[1] for p in points),
                min(p[0] for p in points), max(p[0] for p in points))
    bc_index, pc_groups = defaultdict(list), defaultdict(list)
    for item in bc:
        if canadian_point(item.get("latitude"), item.get("longitude")):
            bc_index[name_key(item["protectedAreaName"])].append(item)
    for item in pc:
        attrs, geometry = item["attributes"], item.get("geometry") or {}
        lat, lon = geometry.get("y"), geometry.get("x")
        if canadian_point(lat, lon) and attrs.get("Accommodation_Type") in {1, 2, 12}:
            pc_groups[name_key(attrs.get("Name_e"))].append((lat, lon))
    pc_index = defaultdict(list)
    for name, points in pc_groups.items():
        pc_index[name] = points
    matched, unmatched = {}, []
    for tenant, targets in catalogs.items():
        for target in targets:
            if not target.get("location_precision") and canadian_point(target.get("latitude"), target.get("longitude")):
                continue
            name = target["name"].removesuffix(" - Camping")
            found = None
            if tenant == "bc":
                candidates = bc_index[name_key(name)]
                if len(candidates) == 1:
                    item = candidates[0]
                    found = {"latitude": item["latitude"], "longitude": item["longitude"],
                             "source_url": item["url"], "precision": "park"}
            else:
                # The reservation prefix disambiguates repeated campground names.
                park, separator, campground = name.partition(" - ")
                park = {"Lake Louise": "Banff"}.get(park, park)
                bounds = park_bounds.get(name_key(park))
                # Name alone is unsafe: Green Point exists on both coasts.
                # The official park envelope is an identity check, not a pin.
                if bounds and separator:
                    points = [p for p in pc_index[name_key(campground)]
                              if bounds[0] <= p[0] <= bounds[1] and bounds[2] <= p[1] <= bounds[3]]
                    point = representative_point(points)
                    if point:
                        found = {"latitude": point[0], "longitude": point[1], "source_url": PC_API, "precision": "campground"}
            if found:
                matched[target["campground_id"]] = {"name": name, **found}
            else:
                unmatched.append({"campground_id": target["campground_id"], "name": name})
    return matched, unmatched


async def download(cache, refresh):
    cache.mkdir(parents=True, exist_ok=True)

    async def cached(name, fetch):
        path = cache / f"{name}.json"
        if path.exists() and not refresh:
            return json.loads(path.read_text(encoding="utf-8"))
        value = await fetch()
        path.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")
        return value

    catalogs = {}
    for tenant in ("bc", "pc"):
        catalogs[tenant] = await cached(f"{tenant}-catalog", GoingToCampClient(tenant=tenant).discover)

    async with httpx.AsyncClient(timeout=30, follow_redirects=False, headers={"User-Agent": "CampFinder-coordinate-reference/1.0"}) as client:
        async def bc_fetch():
            rows = []
            for page in range(1, 11):
                response = await client.get(BC_API, params={"pagination[pageSize]": 2000, "pagination[page]": page,
                    **{f"fields[{i}]": value for i, value in enumerate(("protectedAreaName", "latitude", "longitude", "url"))}})
                response.raise_for_status()
                payload = response.json()
                rows.extend(payload["data"])
                if page >= payload["meta"]["pagination"]["pageCount"]:
                    return rows
                await asyncio.sleep(5)
            raise ValueError("BC location catalog exceeded pagination limit")

        async def pc_fetch():
            rows = []
            for page in range(10):
                response = await client.get(PC_API, params={"where": "1=1", "outFields": "OBJECTID,Name_e,URL_e,Accommodation_Type",
                    "outSR": 4326, "orderByFields": "OBJECTID", "resultOffset": page * 2000, "resultRecordCount": 2000, "f": "json"})
                response.raise_for_status()
                payload = response.json()
                if payload.get("error") or payload.get("spatialReference", {}).get("wkid") != 4326:
                    raise ValueError("Parks Canada location catalog is unavailable or not WGS84")
                rows.extend(payload["features"])
                if not payload.get("exceededTransferLimit"):
                    return rows
                await asyncio.sleep(5)
            raise ValueError("Parks Canada location catalog exceeded pagination limit")

        async def parks_fetch():
            response = await client.get(PC_PARKS_API, params={"where": "1=1", "outFields": "Park_Name_",
                "outSR": 4326, "geometryPrecision": 4, "maxAllowableOffset": 0.001, "f": "json"})
            response.raise_for_status()
            payload = response.json()
            if payload.get("error") or payload.get("exceededTransferLimit") or payload.get("spatialReference", {}).get("wkid") != 4326:
                raise ValueError("Parks Canada boundaries are incomplete or not WGS84")
            return payload["features"]

        return catalogs, await cached("bc-official", bc_fetch), await cached("pc-official", pc_fetch), await cached("pc-parks", parks_fetch)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/canadian-locations.json"))
    parser.add_argument("--cache-dir", type=Path, default=Path("output/location-reference"))
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    catalogs, bc, pc, parks = asyncio.run(download(args.cache_dir, args.refresh))
    matched, unmatched = resolve(catalogs, bc, pc, parks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"generated_at": datetime.now(UTC).isoformat(), "sources": [BC_API, PC_API, PC_PARKS_API],
        "locations": dict(sorted(matched.items()))}, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"matched": len(matched), "unmatched": unmatched}, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
