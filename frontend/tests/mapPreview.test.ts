import assert from "node:assert/strict";
import { test } from "node:test";
import { campgroundPreviewHtml, mapAvailabilityPreviews, combineMapPreviews, previewHeightLimit, previewOffset } from "../src/mapPreview.ts";
import type { AvailabilityWindow } from "../src/types.ts";

const window = (campground: string, arrival: string, departure: string, count: number): AvailabilityWindow => ({
  campground_id: campground, arrival_date: arrival, departure_date: departure,
  match_count: count, last_seen_at: "2026-11-18T16:00:00Z"
});
const campground = { name: "Coast Campground", parkName: "Olympic", stateCode: "WA" };

test("hover totals use the complete aggregate, sorted dates, and the most recent observation", () => {
  const rows = [window("a", "2027-07-09", "2027-07-11", 12000), window("a", "2027-07-02", "2027-07-04", 3100), window("b", "2027-07-02", "2027-07-04", 2)];
  rows[1].last_seen_at = "2026-11-18T17:00:00Z";
  const previews = mapAvailabilityPreviews(rows, null);
  assert.equal(previews.get("a")?.matchCount, 15100);
  assert.equal(previews.get("a")?.lastSeenAt, rows[1].last_seen_at);
  assert.equal(previews.get("a")?.stays[0].arrival_date, "2027-07-02");
  assert.equal(previews.get("b")?.matchCount, 2);
  assert.equal(rows[0].arrival_date, "2027-07-09");
});

test("combined campground previews aggregate categories by stay without joining partial nights", () => {
  const rows = [window("camping", "2027-07-02", "2027-07-04", 3), window("roofed", "2027-07-02", "2027-07-04", 2)];
  const combined = combineMapPreviews([...mapAvailabilityPreviews(rows, null).values()])!;
  assert.equal(combined.matchCount, 5);
  assert.equal(combined.stays.length, 1);
  assert.equal(combined.stays[0].match_count, 5);
  assert.equal(rows[0].match_count, 3);
  assert.equal(combineMapPreviews([]), undefined);
  const partial = [window("camping", "2027-07-02", "2027-07-03", 1), window("roofed", "2027-07-03", "2027-07-04", 1)];
  assert.equal(combineMapPreviews([...mapAvailabilityPreviews(partial, { arrival: "2027-07-02", departure: "2027-07-04" }).values()]), undefined);
});

test("date-filtered previews require one saved stay covering every selected night", () => {
  const rows = [window("a", "2027-07-02", "2027-07-04", 5), window("a", "2027-07-04", "2027-07-05", 7)];
  assert.equal(mapAvailabilityPreviews(rows, { arrival: "2027-07-03", departure: "2027-07-04" }).get("a")?.matchCount, 5);
  assert.equal(mapAvailabilityPreviews(rows, { arrival: "2027-07-02", departure: "2027-07-05" }).size, 0);
  const preview = mapAvailabilityPreviews(rows, { arrival: "2027-07-03", departure: "2027-07-04" }).get("a");
  const html = campgroundPreviewHtml(campground, preview, { stay: { arrival: "2027-07-03", departure: "2027-07-04" }, loaded: true, error: false });
  assert.match(html, /Check-in/);
  assert.match(html, /Check-out/);
  assert.match(html, /5 saved matches/);
  assert.match(html, /Jul 2, 2027/); // Keep the originally verified stay, not only the shorter selection.
});

test("preview dates are bounded and counts describe matches rather than unique sites", () => {
  const rows = [2, 9, 16, 23].map(day => window("a", `2027-07-${String(day).padStart(2, "0")}`, `2027-07-${String(day + 2).padStart(2, "0")}`, 1));
  const html = campgroundPreviewHtml(campground, mapAvailabilityPreviews(rows, null).get("a"), { stay: null, loaded: true, error: false });
  assert.match(html, /4 saved matches/);
  assert.match(html, /\+1 more date pairs/);
  assert.doesNotMatch(html, /Jul 23/);
  assert.doesNotMatch(html, /sites/);
});

test("empty, unavailable, and stale availability are distinct from sold-out inventory", () => {
  assert.match(campgroundPreviewHtml(campground, undefined, { stay: null, loaded: true, error: false }), /No saved availability/);
  assert.match(campgroundPreviewHtml(campground, undefined, { stay: null, loaded: false, error: false }), /Availability not loaded/);
  const preview = mapAvailabilityPreviews([window("a", "2027-07-02", "2027-07-04", 1)], null).get("a");
  const html = campgroundPreviewHtml(campground, preview, { stay: null, loaded: true, error: true });
  assert.match(html, /1 saved match</);
  assert.match(html, /Saved counts may be stale/);
  assert.doesNotMatch(html, /sold out/i);
});

test("provider names cannot inject markup into Leaflet previews", () => {
  const html = campgroundPreviewHtml({ name: '<img src=x onerror="bad()">', parkName: "<script>bad()</script>", stateCode: "A&B", locationPrecision: "park" }, undefined, { stay: null, loaded: true, error: false });
  assert.doesNotMatch(html, /<img|<script/);
  assert.match(html, /&lt;img/);
  assert.match(html, /A&amp;B/);
  assert.match(html, /Park reference location/);
});

test("preview links preserve provider URLs and open in isolated new tabs", () => {
  const mapsUrl = "https://www.google.com/maps/dir/?api=1&destination=47.600000%2C-124.300000&travelmode=driving";
  for (const websiteUrl of [
    "https://www.recreation.gov/camping/campgrounds/232464",
    "https://washington.goingtocamp.com/?resourceLocationId=-2147483648&bookingCategoryId=1",
    "https://campground.example/?name=Coast&region=WA"
  ]) {
    const html = campgroundPreviewHtml(campground, undefined, { stay: null, loaded: true, error: false, mapsUrl, websiteUrl });
    assert.match(html, />Google Maps<\/a>/);
    assert.match(html, />Website<\/a>/);
    assert.ok(html.includes(websiteUrl.replaceAll("&", "&amp;")));
    assert.match(html, /destination=47.600000%2C-124.300000/);
    assert.equal((html.match(/target="_blank" rel="noopener noreferrer"/g) || []).length, 2);
  }
});

test("missing or unsafe preview links are omitted rather than made clickable", () => {
  for (const websiteUrl of [undefined, "", "/relative", "//example.com", "javascript:alert(1)", "java\nscript:alert(1)",
    "data:text/html,<script>alert(1)</script>", "file:///private", "https://user:secret@example.com"]) {
    const html = campgroundPreviewHtml(campground, undefined, { stay: null, loaded: true, error: false, websiteUrl });
    assert.doesNotMatch(html, /<a\s|map-preview-links/);
  }
  const html = campgroundPreviewHtml(campground, undefined, { stay: null, loaded: true, error: false,
    websiteUrl: 'https://example.com/?q=" onmouseover="bad()&other=<script>' });
  assert.doesNotMatch(html, /" onmouseover=|<script>/);
  assert.match(html, /%22/);
});

test("preview placement keeps the entire card inside desktop and mobile maps", () => {
  for (const map of [{ x: 1080, y: 500 }, { x: 300, y: 420 }]) {
    for (const point of [{ x: 2, y: 2 }, { x: map.x - 2, y: 2 }, { x: 2, y: map.y - 2 }, { x: map.x - 2, y: map.y - 2 }, { x: map.x / 2, y: map.y / 2 }]) {
      const card = { width: 276, height: Math.min(240, map.y - 116, previewHeightLimit(point, map)) };
      const offset = previewOffset(point, map, card);
      const center = { x: point.x + offset.x, y: point.y + offset.y };
      assert.ok(center.x - card.width / 2 >= 8);
      assert.ok(center.x + card.width / 2 <= map.x - 8);
      assert.ok(center.y - card.height / 2 >= 88);
      assert.ok(center.y + card.height / 2 <= map.y - 28);
      assert.ok(center.y + card.height / 2 < point.y - 11 || center.y - card.height / 2 > point.y + 11);
    }
  }
});
