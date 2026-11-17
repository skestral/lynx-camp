from urllib.parse import urlencode
import re


def goingtocamp_identity(campground_id: str) -> tuple[int, int]:
    match = re.fullmatch(r"gtc:wa:(-?(?:0|[1-9][0-9]{0,9})):(0|1)", campground_id)
    if not match or not -(2 ** 31) <= int(match[1]) < 2 ** 31 or match[1] == "-0":
        raise ValueError("Invalid Washington State Parks campground identity")
    return int(match[1]), int(match[2])


def provider_key(campground_id: str) -> str:
    if ":" not in campground_id:
        return "recreation"
    parts = campground_id.split(":")
    if len(parts) == 3 and parts[:2] == ["camava", "snoco"] and parts[2].isdigit():
        return "snohomish"
    if campground_id == "activenet:king:66":
        return "king"
    if campground_id == "cedar:skagit:hmsp":
        return "skagit"
    if campground_id.startswith("gtc:wa:"):
        goingtocamp_identity(campground_id)
        return "goingtocamp"
    raise ValueError(f"Unsupported campground provider: {campground_id}")


def provider_name(campground_id: str) -> str:
    return {"snohomish": "Snohomish County Parks", "king": "King County Parks", "skagit": "Skagit County Parks",
            "goingtocamp": "Washington State Parks",
            "recreation": "Recreation.gov"}[provider_key(campground_id)]


def campground_url(campground_id: str, arrival: str | None = None, departure: str | None = None,
                   *, campsite_id: str | None = None) -> str:
    if provider_key(campground_id) == "goingtocamp":
        from datetime import date

        location, category = goingtocamp_identity(campground_id)
        params = {"resourceLocationId": str(location), "bookingCategoryId": str(category),
                  "searchTabGroupId": str(category), "isReserving": "true", "view": "list", "partySize": "1"}
        if campsite_id:
            parts = campsite_id.split(":")
            if (len(parts) != 6 or ":".join(parts[:4]) != campground_id
                    or any(not re.fullmatch(r"-?(?:0|[1-9][0-9]{0,9})", part) for part in parts[4:])):
                raise ValueError("Invalid Washington State Parks campsite identity")
            if any(not -(2 ** 31) <= int(part) < 2 ** 31 or part == "-0" for part in parts[4:]):
                raise ValueError("Invalid Washington State Parks campsite identity")
            params["mapId"] = parts[4]
        if category == 0:
            params["equipmentId"] = "-32768"
        if arrival and departure:
            start, end = date.fromisoformat(arrival), date.fromisoformat(departure)
            if not 1 <= (end - start).days <= 31:
                raise ValueError("Invalid Washington State Parks stay length")
            params.update(startDate=start.isoformat(), endDate=end.isoformat(), nights=str((end - start).days))
        return "https://washington.goingtocamp.com/create-booking/results?" + urlencode(params)
    if provider_key(campground_id) == "recreation":
        return f"https://www.recreation.gov/camping/campgrounds/{campground_id}"
    if provider_key(campground_id) == "skagit":
        return "https://www.explore.skagitcounty.org/skagitcounty/reservation/campgrounds/e43b2789-e411-426f-9d75-b53a499c11ba"
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
