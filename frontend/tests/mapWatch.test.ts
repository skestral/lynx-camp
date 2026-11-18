import { strict as assert } from "node:assert";
import { test } from "node:test";
import type { Target } from "../src/types.ts";
import { addMapWatchTargets, mapWatchTargets, toggleMapWatchTarget, MAP_WATCH_LIMIT } from "../src/mapWatch.ts";

const targets = [
  { id: 1, name: "Coast", active: 1 },
  { id: 2, name: "Cabins", active: 1 },
  { id: 3, name: "Inactive", active: 0 }
] as Target[];

test("map selection is ordered, unique, and restricted to active saved targets", () => {
  assert.deepEqual(mapWatchTargets(targets, [2, 1, 2, 3, 99]).map(target => target.id), [2, 1]);
  assert.deepEqual(addMapWatchTargets(targets, [2], [1, 2, 3, 99]), [2, 1]);
});

test("clicking a selected marker removes it; unavailable targets cannot be added", () => {
  assert.deepEqual(toggleMapWatchTarget(targets, [1], 2), [1, 2]);
  assert.deepEqual(toggleMapWatchTarget(targets, [1, 2], 1), [2]);
  assert.deepEqual(toggleMapWatchTarget(targets, [1], 3), [1]);
  assert.deepEqual(toggleMapWatchTarget(targets, [1], 99), [1]);
});

test("selection survives map filters but drops deleted or deactivated targets", () => {
  assert.deepEqual(mapWatchTargets(targets, [1, 2]).map(target => target.id), [1, 2]);
  assert.deepEqual(mapWatchTargets(targets.filter(target => target.id !== 1), [1, 2]).map(target => target.id), [2]);
  assert.deepEqual(mapWatchTargets(targets.map(target => ({ ...target, active: 0 })), [1, 2]), []);
});

test("bulk selection respects the watch-group API limit without evicting earlier choices", () => {
  const many = Array.from({ length: 510 }, (_, index) => ({ id: index + 1, active: 1 })) as Target[];
  const selected = addMapWatchTargets(many, [510], many.map(target => target.id));
  assert.equal(selected.length, MAP_WATCH_LIMIT);
  assert.equal(selected[0], 510);
  assert.equal(new Set(selected).size, MAP_WATCH_LIMIT);
});
