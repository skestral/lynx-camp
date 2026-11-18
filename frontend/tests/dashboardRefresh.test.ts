import assert from "node:assert/strict";
import { test } from "node:test";
import { createRefreshGate } from "../src/dashboardRefresh.ts";

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>(done => { resolve = done; });
  return { promise, resolve };
}

test("slow dashboard reads never stack live polls", async () => {
  const gate = createRefreshGate(), hold = deferred();
  let calls = 0;
  const first = gate.run(async () => { calls++; await hold.promise; });
  await Promise.resolve();
  for (let i = 0; i < 20; i++) assert.equal(await gate.run(async () => { calls++; }, false), false);
  assert.equal(calls, 1);
  hold.resolve();
  await first;
  assert.equal(await gate.run(async () => { calls++; }, false), true);
  assert.equal(calls, 2);
});

test("full refresh after a write waits for the older poll, then reads fresh data", async () => {
  const gate = createRefreshGate(), hold = deferred();
  const order: string[] = [];
  const live = gate.run(async () => { order.push("old"); await hold.promise; order.push("old finished"); }, false);
  const full = gate.run(async () => { order.push("fresh"); });
  const next = gate.run(async () => { order.push("next fresh"); });
  await Promise.resolve();
  assert.deepEqual(order, ["old"]);
  hold.resolve();
  await Promise.all([live, full, next]);
  assert.deepEqual(order, ["old", "old finished", "fresh", "next fresh"]);
});

test("failed requests release the gate and do not prevent queued recovery", async () => {
  const gate = createRefreshGate(), hold = deferred();
  const failed = gate.run(async () => { await hold.promise; throw Error("offline"); });
  const checked = assert.rejects(failed, /offline/);
  const retry = gate.run(async () => {});
  hold.resolve();
  await checked;
  assert.equal(await retry, true);
});
