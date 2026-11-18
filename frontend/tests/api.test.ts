import assert from "node:assert/strict";
import { test } from "node:test";
import { api } from "../src/api.ts";

test("provider reads allow paced requests without slowing dashboard timeout detection", async (t) => {
  const timeouts: number[] = [];
  t.mock.method(AbortSignal, "timeout", (ms: number) => {
    timeouts.push(ms);
    return new AbortController().signal;
  });
  t.mock.method(globalThis, "fetch", async () => new Response("[]", {
    headers: { "Content-Type": "application/json" }
  }));
  await api.search("Olympic");
  await api.campgroundDetails("232464");
  await api.releaseWindowProfiles(1);
  await api.targets();
  await api.scanConfig();
  assert.deepEqual(timeouts, [300000, 300000, 300000, 15000, 15000]);
});

test("date-filter requests retain their timeout even with an external cancellation signal", async (t) => {
  const timeout = new AbortController(), external = new AbortController();
  let actual: AbortSignal | null = null;
  t.mock.method(AbortSignal, "timeout", () => timeout.signal);
  t.mock.method(globalThis, "fetch", async (_path, options) => {
    actual = options?.signal as AbortSignal;
    timeout.abort(new DOMException("Expired", "TimeoutError"));
    throw new DOMException("Expired", "TimeoutError");
  });
  await assert.rejects(api.resultsForStay("2027-06-04", "2027-06-06", undefined, undefined, external.signal), /request timed out/);
  assert.equal((actual as AbortSignal | null)?.aborted, true);
  assert.equal(external.signal.aborted, false);
});

test("network failures and interrupted response bodies identify the failing endpoint", async (t) => {
  t.mock.method(globalThis, "fetch", async () => { throw new TypeError("Failed to fetch"); });
  await assert.rejects(api.targets(), /\/api\/targets: server unreachable/);
  t.mock.method(globalThis, "fetch", async () => new Response("not json", { headers: { "Content-Type": "application/json" } }));
  await assert.rejects(api.targets(), /\/api\/targets: invalid or interrupted JSON response/);
});
