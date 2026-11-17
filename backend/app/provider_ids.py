from urllib.parse import urlencode


def provider_key(campground_id: str) -> str:
    if ":" not in campground_id:
        return "recreation"
    parts = campground_id.split(":")
    if len(parts) == 3 and parts[:2] == ["camava", "snoco"] and parts[2].isdigit():
        return "snohomish"
    if campground_id == "activenet:king:66":
        return "king"
    raise ValueError(f"Unsupported campground provider: {campground_id}")


def provider_name(campground_id: str) -> str:
    return {"snohomish": "Snohomish County Parks", "king": "King County Parks",
            "recreation": "Recreation.gov"}[provider_key(campground_id)]


def campground_url(campground_id: str, arrival: str | None = None, departure: str | None = None,
                   *, campsite_id: str | None = None) -> str:
    if provider_key(campground_id) == "recreation":
        return f"https://www.recreation.gov/camping/campgrounds/{campground_id}"
    if provider_key(campground_id) == "king":
        facility = "125"
        if campsite_id:
            parts = campsite_id.split(":")
            if len(parts) != 3 or parts[:2] != ["activenet", "king"] or not parts[2].isdigit():
                raise ValueError("Invalid King County campsite identity")
            facility = parts[2]
        return "https://anc.apm.activecommunities.com/kingcountyparks/reservation/landing/search/map/-1?" + urlencode({"facilityId": facility, "attendee": 0})
    params = {"parent_idno": campground_id.split(":")[-1], "reserve_type": "camping"}
    if arrival and departure:
        from datetime import date

        params.update({
            "camping_arrive_date": date.fromisoformat(arrival).strftime("%m/%d/%Y"),
            "camping_depart_date": date.fromisoformat(departure).strftime("%m/%d/%Y"),
            "actiontype": "search", "site_type_idno": "-1",
        })
    return "https://reservations.snocoparks.org/reservation/camping/index.asp?" + urlencode(params)
