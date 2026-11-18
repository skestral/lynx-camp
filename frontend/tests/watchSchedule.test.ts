import { strict as assert } from "node:assert";
import { test } from "node:test";
import { recurringStayPreview, watchArrivalDays } from "../src/watchSchedule.ts";

test("Saturday and one night previews Sunday check-out", () => {
  assert.deepEqual(recurringStayPreview([5], 1), [
    { day: 5, checkIn: "Saturday", checkOut: "Sunday", weeksLater: 0 }
  ]);
});

test("selected days are alternative arrivals, including Sunday-to-Monday rollover", () => {
  assert.deepEqual(recurringStayPreview([6, 5, 5], 1), [
    { day: 5, checkIn: "Saturday", checkOut: "Sunday", weeksLater: 0 },
    { day: 6, checkIn: "Sunday", checkOut: "Monday", weeksLater: 0 }
  ]);
  assert.equal(recurringStayPreview([4], 2)[0].checkOut, "Sunday");
});

test("week-long stays distinguish later weeks from same-day check-out", () => {
  assert.deepEqual(recurringStayPreview([5], 7)[0], { day: 5, checkIn: "Saturday", checkOut: "Saturday", weeksLater: 1 });
  assert.deepEqual(recurringStayPreview([5], 8)[0], { day: 5, checkIn: "Saturday", checkOut: "Sunday", weeksLater: 1 });
  assert.deepEqual(recurringStayPreview([5], 14)[0], { day: 5, checkIn: "Saturday", checkOut: "Saturday", weeksLater: 2 });
});

test("empty or invalid input never previews a made-up stay", () => {
  assert.deepEqual(recurringStayPreview([], 1), []);
  for (const nights of [0, -1, 1.5, 15, NaN, Infinity]) assert.deepEqual(recurringStayPreview([5], nights), []);
  for (const day of [-1, 7, 1.5, NaN]) assert.deepEqual(recurringStayPreview([day], 1), []);
});

test("editing older watches uses the scanner's legacy arrival-day defaults", () => {
  const expected = { "thu-sat": 3, "thu-sun": 3, "fri-sun": 4, "fri-sat-sun": 4,
    "fri-mon": 4, "sat-sun": 5, "sat-mon": 5, "sat-sun-mon": 5, "sun-mon": 6, unknown: 4 };
  for (const [pattern, day] of Object.entries(expected)) {
    assert.deepEqual(watchArrivalDays({ pattern }), [day]);
    assert.deepEqual(watchArrivalDays({ pattern, arrival_weekdays: [] }), [day]);
    assert.deepEqual(watchArrivalDays({ pattern, arrival_weekdays: [0, 6] }), [0, 6]);
  }
});
