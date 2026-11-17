from urllib.parse import urlencode


def provider_key(campground_id: str) -> str:
    if ":" not in campground_id:
        return "recreation"
    parts = campground_id.split(":")
    if len(parts) == 3 and parts[:2] == ["camava", "snoco"] and parts[2].isdigit():
        return "snohomish"
    raise ValueError(f"Unsupported campground provider: {campground_id}")


def provider_name(campground_id: str) -> str:
    return "Snohomish County Parks" if provider_key(campground_id) == "snohomish" else "Recreation.gov"


def campground_url(campground_id: str, arrival: str | None = None, departure: str | None = None) -> str:
    if provider_key(campground_id) == "recreation":
        return f"https://www.recreation.gov/camping/campgrounds/{campground_id}"
    params = {"parent_idno": campground_id.split(":")[-1], "reserve_type": "camping"}
    if arrival and departure:
        from datetime import date

        params.update({
            "camping_arrive_date": date.fromisoformat(arrival).strftime("%m/%d/%Y"),
            "camping_depart_date": date.fromisoformat(departure).strftime("%m/%d/%Y"),
            "actiontype": "search", "site_type_idno": "-1",
        })
    return "https://reservations.snocoparks.org/reservation/camping/index.asp?" + urlencode(params)
