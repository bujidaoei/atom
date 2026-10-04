import assert from "node:assert/strict";
import test from "node:test";
import { ProjectLoader } from "../src/workspace/project-loader.ts";

const tick = () => new Promise<void>(resolve => setTimeout(resolve, 0));

test("burst coalesces; first success displays before trailing read finishes", async () => {
  const reads: ((value: number) => void)[] = [];
  const seen: number[] = [];
  const loader = new ProjectLoader({ read: () => new Promise<number>(resolve => reads.push(resolve)),
    apply: value => seen.push(value), fail: error => { throw error; } });
  const done = loader.refresh();
  await tick();
  for (let i = 0; i < 100; i++) void loader.refresh();
  assert.equal(reads.length, 1);
  reads[0](1);
  await tick();
  assert.deepEqual(seen, [1]);
  assert.equal(reads.length, 2);
  reads[1](2);
  await done;
  assert.deepEqual(seen, [1, 2]);
});

test("dispose aborts and prevents stale application and trailing requests", async () => {
  let signal: AbortSignal | undefined;
  let finish!: (value: number) => void;
  const seen: number[] = [];
  const loader = new ProjectLoader({read: value => { signal = value;
    return new Promise<number>(resolve => { finish = resolve; }); },
    apply: value => seen.push(value), fail: () => assert.fail("disposed error")});
  const done = loader.refresh();
  await tick();
  void loader.refresh();
  loader.dispose();
  assert.equal(signal?.aborted, true);
  finish(1);
  await done;
  await loader.refresh();
  assert.deepEqual(seen, []);
});

test("failure releases slot and an explicit retry succeeds", async () => {
  let calls = 0;
  const seen: number[] = [], errors: unknown[] = [];
  const loader = new ProjectLoader({read: async () => {
    if (++calls === 1) throw new Error("offline"); return calls;
  }, apply: value => seen.push(value), fail: error => errors.push(error)});
  await loader.refresh();
  await loader.refresh();
  assert.equal(errors.length, 1);
  assert.deepEqual(seen, [2]);
});

test("deadline aborts real signal-aware read and reports retryable timeout", async () => {
  const errors: unknown[] = [];
  const loader = new ProjectLoader({timeoutMs: 5, read: signal => new Promise<never>((_, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason), {once:true});
  }), apply: () => assert.fail("timed out"), fail: error => errors.push(error)});
  await loader.refresh();
  assert.match(String(errors[0]), /超时/);
});
