import assert from "node:assert/strict";
import test from "node:test";

import {
  QuoteApiError,
  computeFileSha256,
  createQuoteRequest,
  issueModelUpload,
  uploadModelToStorage,
  validateModelSelection,
} from "./quote-api.ts";

test("computes the lowercase hex SHA-256 digest of a file's contents", async () => {
  const file = new File(["hello world"], "hello.stl");
  const digest = await computeFileSha256(file);
  assert.equal(
    digest,
    "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
  );
  assert.match(digest, /^[0-9a-f]{64}$/);
});

test("rejects unsupported, empty, oversized, and too-numerous file selections", () => {
  const good = new File(["abc"], "part.stl");
  const badFormat = new File(["abc"], "part.exe");
  const empty = new File([], "empty.obj");
  const oversized = new File(["x"], "big.step");
  Object.defineProperty(oversized, "size", { value: 100 * 1024 * 1024 + 1 });

  const result = validateModelSelection([good, badFormat, empty, oversized]);
  assert.deepEqual(result.accepted, [good]);
  assert.deepEqual(
    result.rejected.map((entry) => entry.reason),
    ["unsupported_format", "empty_file", "file_too_large"],
  );
  assert.equal(result.tooMany, false);

  const tooManyResult = validateModelSelection([good, good, good, good, good, good]);
  assert.equal(tooManyResult.tooMany, true);
});

test("builds the storage FormData with every signed field first and the file last", async () => {
  const originalFetch = globalThis.fetch;
  let capturedBody: FormData | undefined;
  globalThis.fetch = async (_input, init) => {
    capturedBody = init?.body as FormData;
    return new Response(null, { status: 204 });
  };
  try {
    const file = new File(["model bytes"], "model.stl");
    await uploadModelToStorage(
      {
        url: "https://storage.example.com/xxx-private-models",
        fields: { key: "models/original/a/b/c/source", "Content-Type": "application/octet-stream" },
        expiresAt: "2026-01-01T00:00:00Z",
      },
      file,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }

  const entries = Array.from(capturedBody!.entries());
  assert.deepEqual(
    entries.slice(0, 2).map(([name]) => name),
    ["key", "Content-Type"],
  );
  const [lastName, lastValue] = entries[entries.length - 1]!;
  assert.equal(lastName, "file");
  assert.ok(lastValue instanceof File);
});

test("does not send credentials or custom headers to the storage endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let capturedInit: RequestInit | undefined;
  globalThis.fetch = async (_input, init) => {
    capturedInit = init;
    return new Response(null, { status: 201 });
  };
  try {
    await uploadModelToStorage(
      { url: "https://storage.example.com/upload", fields: { key: "value" }, expiresAt: "2026-01-01T00:00:00Z" },
      new File(["a"], "a.3mf"),
    );
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(capturedInit?.credentials, undefined);
  assert.equal(capturedInit?.headers, undefined);
});

test("copies the signed CSRF cookie into quote-request mutation headers", async () => {
  const originalFetch = globalThis.fetch;
  let capturedUrl = "";
  let capturedInit: RequestInit | undefined;
  globalThis.fetch = async (input, init) => {
    capturedUrl = String(input);
    capturedInit = init;
    return Response.json(
      {
        id: "00000000-0000-0000-0000-000000000001",
        buyerId: "00000000-0000-0000-0000-000000000002",
        status: "draft",
        version: 1,
        submittedAt: null,
        createdAt: "2026-01-01T00:00:00Z",
        updatedAt: "2026-01-01T00:00:00Z",
        assets: [],
      },
      { status: 201 },
    );
  };
  try {
    await createQuoteRequest("00000000-0000-0000-0000-000000000003", "xxx_csrf=signed%3Atoken");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(capturedUrl, "/api/v1/quote-requests");
  assert.equal(capturedInit?.method, "POST");
  assert.equal(capturedInit?.credentials, "same-origin");
  assert.equal(capturedInit?.cache, "no-store");
  assert.equal(new Headers(capturedInit?.headers).get("x-csrf-token"), "signed:token");
  assert.deepEqual(JSON.parse(String(capturedInit?.body)), {
    clientToken: "00000000-0000-0000-0000-000000000003",
  });
});

test("refuses to send a mutation without a signed CSRF cookie", async () => {
  await assert.rejects(
    () => createQuoteRequest("00000000-0000-0000-0000-000000000003", "other=1"),
    (error: unknown) => error instanceof QuoteApiError && error.status === 401,
  );
});

test("rejects an invalid upload-intent payload instead of returning it", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    Response.json({ asset: { id: "only-an-id" } }, { status: 201 });
  try {
    await assert.rejects(
      () =>
        issueModelUpload(
          "00000000-0000-0000-0000-000000000001",
          {
            clientToken: "00000000-0000-0000-0000-000000000002",
            filename: "part.stl",
            sizeBytes: 1024,
            sha256: "a".repeat(64),
          },
          "xxx_csrf=signed%3Atoken",
        ),
      (error: unknown) => error instanceof QuoteApiError && error.status === 502,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
