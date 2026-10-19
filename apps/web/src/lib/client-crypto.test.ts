import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import test from "node:test";
import { sha256Hex, submissionId } from "./client-crypto.ts";

for (const [name, provider] of [
  ["native Web Crypto", globalThis.crypto],
  ["LAN HTTP fallback", {}],
] as const) {
  test(`${name} computes the exact file SHA-256`, async () => {
    for (const bytes of [
      new Uint8Array(),
      new TextEncoder().encode("abc"),
      new Uint8Array(Array.from({ length: 1025 }, (_, i) => i % 256)),
    ]) {
      assert.equal(
        await sha256Hex(bytes.buffer, provider),
        createHash("sha256").update(bytes).digest("hex"),
      );
    }
  });
}

test("LAN HTTP upload IDs use secure randomness and UUID v4 formatting", () => {
  const provider = { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) };
  const ids = Array.from({ length: 50 }, () => submissionId(provider));
  assert.equal(new Set(ids).size, 50);
  for (const id of ids) {
    assert.match(id, /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
  }
});

test("native upload IDs are preserved", () => {
  const id = "e0cd1196-55c3-48a0-a3eb-04c6249aab8b";
  assert.equal(submissionId({ randomUUID: () => id }), id);
});

test("upload IDs fail clearly if the browser has no secure randomness", () => {
  assert.throws(() => submissionId({}), /secure upload IDs/);
});
