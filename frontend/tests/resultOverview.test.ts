import assert from "node:assert/strict";
import { test } from "node:test";
import { api } from "../src/api.ts";
import { childGrouping, groupKey, groupScope } from "../src/resultOverview.ts";
import type { ResultOverviewGroup } from "../src/types.ts";

test("drill-down keeps search, status, map dates, and the read boundary", () => {
  const filters = { view: "active" as const, search: "cabin", arrival: "2027-07-03", departure: "2027-07-04" };
  const campground = { park_name: "Example", campground_id: "gtc:wa:1:2" } as ResultOverviewGroup;
  const scope = groupScope(filters, campground, 15008);
  assert.deepEqual(scope, { ...filters, ...campground, max_result_id: 15008 });
  assert.equal(childGrouping("park", scope), "campground");
  assert.equal(childGrouping("campground", scope), "stay");
  const stay = groupScope(scope, { arrival_date: "2027-07-02", departure_date: "2027-07-04" } as ResultOverviewGroup, 15008);
  assert.equal(childGrouping("stay", stay), "items");
  assert.equal(stay.arrival, "2027-07-03");
  assert.equal(stay.exact_arrival, "2027-07-02");
});

test("date-first groups drill into campgrounds; equal names do not share identity", () => {
  const date = groupScope({ view: "all" }, { arrival_date: "2027-07-02", departure_date: "2027-07-04" } as ResultOverviewGroup, 5);
  assert.equal(childGrouping("stay", date), "campground");
  assert.equal(childGrouping("campground", groupScope(date, { campground_id: "other" } as ResultOverviewGroup, 5)), "items");
  assert.notEqual(groupKey({ campground_id: "one", campground_name: "Same" } as ResultOverviewGroup),
    groupKey({ campground_id: "two", campground_name: "Same" } as ResultOverviewGroup));
});

test("API encodes scoped reads and never expands a dismissal into downloaded IDs", async t => {
  const calls: { path: string; options?: RequestInit }[] = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path: String(path), options });
    return new Response("{}", { headers: { "Content-Type": "application/json" } });
  });
  const filters = { view: "active" as const, park_name: "Rainier & Coast", search: "%_", max_result_id: 15008 };
  await api.resultOverview({ ...filters, group_by: "campground", sort: "arrival", limit: 25 });
  assert.equal(new URL(calls[0].path, "http://test").searchParams.get("park_name"), "Rainier & Coast");
  await api.dismissResultScope(filters);
  assert.deepEqual(JSON.parse(String(calls[1].options?.body)), { filters });
});
