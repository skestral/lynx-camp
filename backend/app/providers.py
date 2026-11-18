"""Provider routing preserves legacy Recreation.gov IDs in existing backups."""
from datetime import date

from .camava import SnohomishClient
from .activenet import KingCountyClient, RequestGate
from .cedar import SkagitCountyClient
from .goingtocamp import GoingToCampClient
from .provider_ids import provider_key
from .provider_registry import GTC_TENANTS, USEDIRECT_TENANTS, is_goingtocamp
from .usedirect import UseDirectClient
from .recreation import RecreationClient


class CampgroundClient(RecreationClient):
    def __init__(self, store=None):
        super().__init__()
        self.snohomish = SnohomishClient()
        self.king = KingCountyClient()
        self.skagit = SkagitCountyClient()
        self.washington = GoingToCampClient(store)
        self.gtc = {tenant: GoingToCampClient(store, tenant=tenant) for tenant in GTC_TENANTS if tenant != "wa"}
        self.usedirect = {tenant: UseDirectClient(tenant, store) for tenant in USEDIRECT_TENANTS}

    def gtc_client(self, tenant: str):
        return self.washington if tenant == "wa" else self.gtc[tenant]

    def source_client(self, source_id: str):
        for tenant, config in USEDIRECT_TENANTS.items():
            if config["source"] == source_id:
                return self.usedirect[tenant]
        return next((self.gtc_client(tenant) for tenant, config in GTC_TENANTS.items() if config["source"] == source_id), None)

    async def ensure_provider_access(self, campground_id: str):
        if is_goingtocamp(provider_key(campground_id)):
            await self.gtc_client(campground_id.split(":")[1]).ensure_access()
        elif provider_key(campground_id).startswith("ud_"):
            await self.usedirect[campground_id.split(":")[1]].ensure_access()

    async def discover_external(self, source_id: str) -> list[dict]:
        if adapter := self.source_client(source_id):
            return await adapter.discover()
        if source_id == "snohomish-county-parks":
            return await self.snohomish.discover()
        if source_id == "king-county-parks":
            return await self.king.discover()
        if source_id == "skagit-county-parks":
            return await self.skagit.discover()
        raise ValueError("This provider does not support discovery yet")

    async def trip_availability(self, campground_id: str, arrival: date, departure: date,
                                before_request: RequestGate | None = None):
        if provider_key(campground_id).startswith("ud_"):
            return await self.usedirect[campground_id.split(":")[1]].trip_availability(campground_id, arrival, departure, before_request)
        if is_goingtocamp(provider_key(campground_id)):
            return await self.gtc_client(campground_id.split(":")[1]).trip_availability(campground_id, arrival, departure, before_request)
        if provider_key(campground_id) == "skagit":
            return await self.skagit.trip_availability(campground_id, arrival, departure, before_request)
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
