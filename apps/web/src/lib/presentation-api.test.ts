import assert from "node:assert/strict";
import test from "node:test";
import { admitPresentation, parsePresentationEntry } from "./presentation-api.ts";

const data = {
  id: "11111111-1111-4111-8111-111111111111",
  requestId: "22222222-2222-4222-8222-222222222222",
  status: "waiting", version: 1, filenames: ["coaster.stl"],
  referenceCostPaise: 10725, durationSeconds: 5340, specification: null,
  submittedAt: "2026-10-21T00:00:00Z", approvedAt: null,
  progressBps: 0, reason: null, free: true,
};

test("free queue preserves server measured cost and duration", () => {
  const entry = parsePresentationEntry(data);
  assert.equal(entry.referenceCostPaise, 10725);
  assert.equal(entry.durationSeconds, 5340);
  assert.equal(entry.free, true);
});

test("free queue rejects invalid money, duration, progress and workflow states", () => {
  for (const change of [
    { referenceCostPaise: -1 }, { referenceCostPaise: "10725" },
    { durationSeconds: 0 }, { progressBps: 10001 },
    { status: "payment_pending" }, { free: false }, { version: 0 },
  ]) assert.throws(() => parsePresentationEntry({ ...data, ...change }));
});

test("owner admission sends version and CSRF, without client price or payment assertions", async () => {
  const originalFetch = globalThis.fetch;
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
  Object.defineProperty(globalThis, "document", { configurable: true, value: { cookie: "xxx_csrf=signed-test-token" } });
  try {
    globalThis.fetch = async (path, options) => {
      assert.equal(path, `/api/v1/presentation/entries/${data.id}/admit`);
      assert.deepEqual(JSON.parse(String(options?.body)), { expectedVersion: 1 });
      assert.equal((options?.headers as Record<string, string>)["X-CSRF-Token"], "signed-test-token");
      return new Response(JSON.stringify({ ...data, status: "approved", version: 2 }), { status: 200 });
    };
    assert.equal((await admitPresentation(parsePresentationEntry(data))).status, "approved");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalDocument) Object.defineProperty(globalThis, "document", originalDocument);
    else Reflect.deleteProperty(globalThis, "document");
  }
});
