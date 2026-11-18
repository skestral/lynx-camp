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
