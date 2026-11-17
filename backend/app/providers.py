"""Provider routing preserves legacy Recreation.gov IDs in existing backups."""
from datetime import date

from .camava import SnohomishClient
from .activenet import KingCountyClient, RequestGate
from .provider_ids import provider_key
from .recreation import RecreationClient


class CampgroundClient(RecreationClient):
    def __init__(self):
        super().__init__()
        self.snohomish = SnohomishClient()
        self.king = KingCountyClient()

    async def discover_external(self, source_id: str) -> list[dict]:
        if source_id == "snohomish-county-parks":
            return await self.snohomish.discover()
        if source_id == "king-county-parks":
            return await self.king.discover()
        raise ValueError("This provider does not support discovery yet")

    async def trip_availability(self, campground_id: str, arrival: date, departure: date,
                                before_request: RequestGate | None = None):
        if provider_key(campground_id) == "king":
            return await self.king.trip_availability(campground_id, arrival, departure, before_request)
        if provider_key(campground_id) == "snohomish":
            if before_request:
                await before_request("Checking stay availability")
            return await self.snohomish.trip_availability(campground_id, arrival, departure)
        raise ValueError("This provider uses monthly availability")

    async def monthly_availability(self, campground_id: str, month: date):
        if provider_key(campground_id) != "recreation":
            raise ValueError("This provider requires an exact stay search")
        return await super().monthly_availability(campground_id, month)

    async def campground_details(self, campground_id: str):
        if provider_key(campground_id) != "recreation":
            return None
        return await super().campground_details(campground_id)
