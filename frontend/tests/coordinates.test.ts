import { strict as assert } from "node:assert";
import { test } from "node:test";
import { coordinatePair } from "../src/coordinates.ts";

test("missing, placeholder and invalid coordinates never produce a map pin", () => {
  for (const [lat, lon] of [[null, null], [undefined, -123], ["", ""], [" ", -123], [0, 0], ["0", "0"],
    [true, -123], [50, false], [NaN, -123], [50, Infinity], [91, -123], [50, -181], [[], []]]) {
    assert.equal(coordinatePair(lat, lon), null);
  }
});

test("valid Canadian coordinates and legitimate equator/meridian points are retained", () => {
  assert.deepEqual(coordinatePair("50.1", "-123.2"), [50.1, -123.2]);
  assert.deepEqual(coordinatePair(0, 40), [0, 40]);
  assert.deepEqual(coordinatePair(50, 0), [50, 0]);
});
