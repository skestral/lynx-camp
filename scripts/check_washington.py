"""Bounded, read-only Washington Camping and Roofed compatibility check."""
import argparse
import asyncio
from datetime import UTC, date, datetime
import json

from backend.app.goingtocamp import GoingToCampClient
from backend.app.provider_errors import ProviderResponseError
from backend.app.recreation import RateLimitError


class DiagnosticClient(GoingToCampClient):
    async def _request(self, path, params=None, before_request=None):
        payload = await super()._request(path, params, before_request)
        if path == "/availability/map" and isinstance(payload, dict):
            resources = payload.get("resourceAvailabilities", {})
            print(json.dumps({"map": params["mapId"], "daily": params["getDailyAvailability"],
                "resources": len(resources), "record_lengths": sorted({len(values) for values in resources.values()}),
                "sample": {key: [{k: v for k, v in entry.items() if k in {"availability", "date", "startDate", "endDate"}}
                                  for entry in values[:4]] for key, values in list(resources.items())[:2]}}), flush=True)
        return payload


async def check(arrival, departure):
    client = DiagnosticClient()
    requests = 0

    async def gate(stage):
        nonlocal requests
        if requests >= 30:
            raise RuntimeError("Diagnostic request limit reached")
        requests += 1
        print(json.dumps({"request": requests, "stage": stage}), flush=True)

    catalog = await client.catalog(gate)
    print(json.dumps({"catalog_count": len(catalog),
                      "camping_count": sum(key.endswith(":0") for key in catalog),
                      "roofed_count": sum(key.endswith(":1") for key in catalog)}), flush=True)
    for park, category in (("Bogachiel", 0), ("Lincoln Rock", 1)):
        matches = [target for key, target in catalog.items()
                   if key.endswith(f":{category}") and target["name"].casefold().startswith(park.casefold() + " ")]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one {park} target in category {category}")
        target = matches[0]
        sites = await client.trip_availability(target["campground_id"], arrival, departure, gate)
        print(json.dumps({"target": target, "arrival": arrival.isoformat(), "departure": departure.isoformat(),
                          "count": len(sites), "sample": [{"id": site.campsite_id, "site": site.site,
                          "type": site.campsite_type, "booking_url": site.booking_url} for site in sites[:3]]}), flush=True)
    print(json.dumps({"status": "completed", "requests": requests}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow up to 30 paced provider GET requests.")
    parser.add_argument("--arrival", type=date.fromisoformat, required=True)
    parser.add_argument("--departure", type=date.fromisoformat, required=True)
    parser.add_argument("--not-before", type=datetime.fromisoformat,
                        help="Existing cooldown timestamp with timezone; this helper does not read appdata.")
    args = parser.parse_args()
    if not args.live:
        parser.error("No requests sent. Pass --live for the explicit provider check.")
    if args.arrival < date.today() or not 1 <= (args.departure - args.arrival).days <= 3:
        parser.error("Choose a future stay of one to three nights.")
    if args.not_before and (args.not_before.tzinfo is None or datetime.now(UTC) < args.not_before):
        parser.error("The supplied cooldown has not elapsed or has no timezone.")
    try:
        asyncio.run(check(args.arrival, args.departure))
    except (ProviderResponseError, RateLimitError, RuntimeError) as exc:
        print(json.dumps({"status": "stopped", "reason": str(exc)}), flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
