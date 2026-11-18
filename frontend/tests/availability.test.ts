import { strict as assert } from "node:assert";
import { test } from "node:test";
import { selectedStay, coversStay, availabilityCounts, availableStays } from "../src/availability.ts";

const windows = [
  { campground_id: "coast", arrival_date: "2027-07-02", departure_date: "2027-07-04", match_count: 3, last_seen_at: "" },
  { campground_id: "mountain", arrival_date: "2027-07-02", departure_date: "2027-07-04", match_count: 2, last_seen_at: "" },
  { campground_id: "coast", arrival_date: "2027-07-03", departure_date: "2027-07-05", match_count: 1, last_seen_at: "" }
];

test("blank dates reset the map; a single date is one night, including DST and year boundaries", () => {
  assert.deepEqual(selectedStay("", ""), { stay: null, error: "" });
  assert.deepEqual(selectedStay("2027-03-14", "").stay, { arrival: "2027-03-14", departure: "2027-03-15" });
  assert.equal(selectedStay("2027-12-31", "").stay?.departure, "2028-01-01");
  assert.equal(selectedStay("2028-02-28", "").stay?.departure, "2028-02-29");
});

test("invalid, incomplete and reversed dates do not silently show all matches", () => {
  for (const [arrival, departure] of [["", "2027-07-04"], ["2027-02-30", ""], ["2027-07-04", "2027-07-04"], ["2027-07-05", "2027-07-04"]]) {
    assert.equal(selectedStay(arrival, departure).stay, null);
    assert.ok(selectedStay(arrival, departure).error);
  }
});

test("check-out is exclusive and a full stay cannot be assembled from partial matches", () => {
  assert.equal(coversStay(windows[0], { arrival: "2027-07-04", departure: "2027-07-05" }), false);
  assert.equal(availabilityCounts(windows, { arrival: "2027-07-02", departure: "2027-07-05" }).size, 0);
  assert.deepEqual([...availabilityCounts(windows, { arrival: "2027-07-03", departure: "2027-07-04" })], [["coast", 4], ["mountain", 2]]);
});

test("saved stay options are sorted and count distinct campgrounds, not sites", () => {
  const stays = availableStays([...windows].reverse().concat(windows[0]));
  assert.equal(stays.length, 2);
  assert.equal(stays[0].key, "2027-07-02/2027-07-04");
  assert.equal(stays[0].campgroundCount, 2);
  assert.equal(stays[1].campgroundCount, 1);
});
