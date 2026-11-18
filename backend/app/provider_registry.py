"""Allowlisted reservation services. Tenant IDs are part of persisted result IDs."""

GTC_TENANTS = {
    "wa": {"name": "Washington State Parks", "source": "washington-state-parks",
           "host": "washington.goingtocamp.com", "state": "WA", "timezone": "America/Los_Angeles", "categories": (0, 1)},
    "tacoma": {"name": "Tacoma Power Parks", "source": "tacoma-power-parks",
               "host": "tacomapower.goingtocamp.com", "state": "WA", "timezone": "America/Los_Angeles", "categories": (0,)},
    "bc": {"name": "BC Parks", "source": "bc-parks",
           "host": "camping.bcparks.ca", "state": "BC", "timezone": "America/Vancouver", "categories": (0,)},
    "pc": {"name": "Parks Canada", "source": "parks-canada",
           "host": "reservation.pc.gc.ca", "state": "CAN", "timezone": "America/Toronto", "categories": (0,)},
}

USEDIRECT_TENANTS = {
    "metro": {"name": "Oregon Metro", "source": "oregon-metro", "state": "OR",
              "base": "https://oregonrdr.usedirect.com/oregonmetrordr",
              "booking": "https://reservemetro.usedirect.com/MetroWeb/Facilities/SearchViewUnitAvailabity.aspx"},
    "ca": {"name": "California State Parks", "source": "reserve-california", "state": "CA",
           "base": "https://california-rdr.prod.cali.rd12.recreation-management.tylerapp.com",
           "booking": "https://www.reservecalifornia.com"},
}


def gtc_provider_key(tenant: str) -> str:
    if tenant not in GTC_TENANTS:
        raise ValueError("Unsupported GoingToCamp tenant")
    return "goingtocamp" if tenant == "wa" else f"gtc_{tenant}"


def is_goingtocamp(provider: str) -> bool:
    return provider in {gtc_provider_key(tenant) for tenant in GTC_TENANTS}


def gtc_state_key(tenant: str, suffix="connection") -> str:
    if tenant.startswith("ud_") and tenant[3:] in USEDIRECT_TENANTS:
        return f"usedirect_{tenant[3:]}_{suffix}"
    gtc_provider_key(tenant)
    return f"goingtocamp_{suffix}" if tenant == "wa" else f"goingtocamp_{tenant}_{suffix}"
