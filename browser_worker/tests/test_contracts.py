import unittest
from urllib.parse import urlencode

from pydantic import ValidationError

from browser_worker.contracts import ExpectedSearch, InspectionError, is_provider_url, validate_submitted_search


def search(category="Camping"):
    return ExpectedSearch(park="Example Park", resource_location_id="-123",
                          category=category, arrival="2026-11-28", departure="2026-11-30")


def search_url(expected=None, **overrides):
    expected = expected or search()
    category = "0" if expected.category == "Camping" else "1"
    params = dict(resourceLocationId=expected.resource_location_id, bookingCategoryId=category,
                  searchTabGroupId=category, startDate=expected.arrival.isoformat(),
                  endDate=expected.departure.isoformat(), nights="2", isReserving="true", view="list")
    params.update(overrides)
    return "https://washington.goingtocamp.com/create-booking/results?" + urlencode(params)


class ContractTests(unittest.TestCase):
    def test_camping_and_roofed_require_the_submitted_category(self):
        for category in ("Camping", "Roofed"):
            expected = search(category)
            result = validate_submitted_search(search_url(expected), expected)
            self.assertEqual(result["bookingCategoryId"], "0" if category == "Camping" else "1")
        with self.assertRaises(InspectionError):
            validate_submitted_search(search_url(), search("Roofed"))

    def test_each_mismatch_is_unknown(self):
        for field in ("resourceLocationId", "bookingCategoryId", "searchTabGroupId", "startDate",
                      "endDate", "nights", "isReserving", "view"):
            for value in ("", "different"):
                with self.subTest(field=field, value=value), self.assertRaises(InspectionError):
                    validate_submitted_search(search_url(**{field: value}), search())
            with self.assertRaises(InspectionError):
                validate_submitted_search(search_url() + f"&{field}=duplicate", search())

    def test_only_exact_https_provider_results_are_accepted(self):
        for url in ("http://washington.goingtocamp.com", "https://washington.goingtocamp.com.evil.test",
                    "https://user@washington.goingtocamp.com", "https://washington.goingtocamp.com:80",
                    "https://[broken", "about:blank"):
            with self.subTest(url=url):
                self.assertFalse(is_provider_url(url))
                with self.assertRaises(InspectionError):
                    validate_submitted_search(url, search())
        with self.assertRaises(InspectionError):
            validate_submitted_search(search_url().replace("/create-booking/results", "/account"), search())

    def test_stay_validation_and_rendered_date_label(self):
        self.assertEqual(search().results_label(), "Search results for Saturday, November 28, 2026 and Monday, November 30, 2026")
        for changes in ({"departure": "2026-11-28"}, {"departure": "2027-01-01"},
                        {"park": " "}, {"category": "Day Use"}, {"resource_location_id": "../123"}, {"unknown": True}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                ExpectedSearch.model_validate({**search().model_dump(), **changes})
