import { strict as assert } from "node:assert";
import { test } from "node:test";
import { groupMapLocations, locationKey, locationWatchIds, toggleLocationWatchIds, listingStatus, parkColors } from "../src/mapLocations.ts";
import type { CampgroundMapPoint } from "../src/mapLocations.ts";

function point(campgroundId: string, name: string, targetId: number | null = 1): CampgroundMapPoint {
  return { id: campgroundId, campgroundId, name, targetId, imported: targetId !== null, active: targetId ? 1 : 0,
    latitude: 47, longitude: -123, parkName: "Washington State Parks", stateCode: "WA", bookingUrl: "https://example.com",
    activeResultCount: 2, resultCount: 2 };
}

test("Camping and Roofed at one provider location share a pin and both watch members", () => {
  const points = [point("gtc:wa:-123:1", "Coast (Cabins) - Roofed", 2), point("gtc:wa:-123:0", "Coast - Camping", 1)];
  const [location] = groupMapLocations(points);
  assert.equal(location.name, "Coast");
  assert.equal(location.members.length, 2);
  assert.equal(location.activeResultCount, 4);
  assert.deepEqual(locationWatchIds(location), [1, 2]);
  assert.deepEqual(toggleLocationWatchIds([], locationWatchIds(location)), [1, 2]);
  assert.deepEqual(toggleLocationWatchIds([1], locationWatchIds(location)), [1, 2]);
  assert.deepEqual(toggleLocationWatchIds([1, 2, 9], locationWatchIds(location)), [9]);
  assert.equal(points[0].name, "Coast (Cabins) - Roofed");
});

test("Rainier has five provider listings at three known locations, not missing pins", () => {
  const locations = groupMapLocations([
    point("232466", "Cougar Rock Campground"), point("232510", "Cougar Rock Group Campground", 2),
    point("232465", "Ohanapecosh Campground", 3), point("232509", "Ohanapecosh Group Campground", 4),
    point("259031", "White River Campground", 5)
  ]);
  assert.equal(locations.length, 3);
  assert.equal(locations.reduce((total, location) => total + location.members.length, 0), 5);
  assert.equal(locations[0].name, "Cougar Rock Campground");
});

test("matching names or coordinates alone do not merge unrelated campgrounds or tenants", () => {
  assert.notEqual(locationKey("gtc:wa:5:0"), locationKey("gtc:bc:5:0"));
  assert.equal(groupMapLocations([point("10", "Same"), point("11", "Same"), point("gtc:bc:5:0", "Same")]).length, 3);
  assert.equal(groupMapLocations([point("gtc:wa:5:0", "Same"), { ...point("gtc:wa:5:1", "Same"), parkName: "Other" }]).length, 2);
});

test("missing imports and paused targets are labeled and never silently enabled", () => {
  const missing = point("gtc:wa:5:0", "Camping", null);
  const paused = { ...point("gtc:wa:5:1", "Roofed", 2), active: 0 };
  assert.equal(listingStatus(missing), "Not imported");
  assert.equal(listingStatus(paused), "Paused target");
  assert.deepEqual(locationWatchIds(groupMapLocations([missing, paused])[0]), []);
  assert.deepEqual(toggleLocationWatchIds([9], []), [9]);
  assert.equal(toggleLocationWatchIds([1], [2, 3], 2).length, 2);
});

test("the park palette is distinct across the bundled groups and stable when reordered", () => {
  const parks = ["Olympic", "Rainier", "Cascades", "Crater Lake", "Glacier", "Yellowstone", "Grand Teton", "Washington State Parks"];
  const colors = parkColors(parks);
  assert.equal(new Set(colors.values()).size, parks.length);
  assert.deepEqual(colors, parkColors([...parks].reverse()));
});
