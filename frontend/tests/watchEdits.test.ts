import { strict as assert } from "node:assert";
import { test } from "node:test";
import { watchChanges } from "../src/watchEdits.ts";
import type { Watch } from "../src/types.ts";

const watch = { name: "Weekend", mode: "specific", pattern: "fri-sun", nights: 2, arrival_weekdays: null,
  alerts_enabled: 0, cart_assist_enabled: 0, site_filters: { site_type: "", site: "", loop: "", min_people: null }
} as Watch;

test("alert-only edit preserves legacy exact-date fields and missing filter defaults", () => {
  assert.deepEqual(watchChanges([watch], { name: "Weekend", mode: "specific", pattern: "specific", nights: 1,
    arrival_weekdays: null, alerts_enabled: true, cart_assist_enabled: false,
    site_filters: { ...watch.site_filters, equipment: "", vehicle_length_ft: null, campsite_ids: [] }
  }), { alerts_enabled: true });
});

test("regional changes still apply a shared value when any member differs", () => {
  assert.deepEqual(watchChanges([watch, { ...watch, name: "Different", alerts_enabled: 1 }], {
    name: "Weekend", alerts_enabled: false, site_filters: { ...watch.site_filters, equipment: "tent" }
  }), { name: "Weekend", alerts_enabled: false, site_filters: { ...watch.site_filters, equipment: "tent" } });
});

test("switching date modes retains all newly selected criteria", () => {
  assert.deepEqual(watchChanges([watch], { mode: "weekend", nights: 3, pattern: "fri-mon", arrival_weekdays: [4] }),
    { mode: "weekend", nights: 3, pattern: "fri-mon", arrival_weekdays: [4] });
});
