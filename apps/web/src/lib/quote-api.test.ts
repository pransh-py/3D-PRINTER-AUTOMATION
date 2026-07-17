import assert from "node:assert/strict";
import test from "node:test";

import {
  QuoteApiError,
  computeFileSha256,
  createQuoteRequest,
  issueModelUpload,
  listQuoteRequests,
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
        latestAnalysis: null,
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

function baseQuoteRequestPayload(latestAnalysis: unknown): unknown {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    buyerId: "00000000-0000-0000-0000-000000000002",
    status: "analysis_ready",
    version: 1,
    submittedAt: "2026-01-01T00:00:00Z",
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    assets: [],
    latestAnalysis,
  };
}

function validAnalysisAssetResultPayload(): unknown {
  return {
    assetId: "00000000-0000-0000-0000-000000000010",
    status: "validated",
    detectedFormat: "stl",
    verifiedSha256: "a".repeat(64),
    dimensionsUm: [10_000, 20_000, 30_000],
    triangleCount: 1200,
    objectCount: 1,
    fitsBuildVolume: true,
    warningCodes: [],
    filamentMg: 4500,
    durationSeconds: 12,
    failureCode: null,
  };
}

function validAnalysisRunPayload(): unknown {
  return {
    id: "00000000-0000-0000-0000-000000000020",
    requestVersion: 1,
    status: "succeeded",
    attemptCount: 1,
    validatorVersion: "orcaslicer-2.1.0",
    slicerName: "OrcaSlicer",
    slicerVersion: "2.1.0",
    profileSha256: "b".repeat(64),
    queuedAt: "2026-01-01T00:00:00Z",
    startedAt: "2026-01-01T00:00:01Z",
    completedAt: "2026-01-01T00:00:05Z",
    failureCode: null,
    assets: [validAnalysisAssetResultPayload()],
  };
}

async function fetchQuoteRequestList(payload: unknown) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    Response.json({ items: [payload], total: 1, limit: 20, offset: 0 }, { status: 200 });
  try {
    return await listQuoteRequests();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

test("parses a quote request with a valid, non-null latest analysis", async () => {
  const list = await fetchQuoteRequestList(baseQuoteRequestPayload(validAnalysisRunPayload()));
  const latestAnalysis = list.items[0]!.latestAnalysis;
  assert.ok(latestAnalysis !== null);
  assert.equal(latestAnalysis.status, "succeeded");
  assert.equal(latestAnalysis.requestVersion, 1);
  assert.equal(latestAnalysis.assets.length, 1);
  const asset = latestAnalysis.assets[0]!;
  assert.equal(asset.status, "validated");
  assert.deepEqual(asset.dimensionsUm, [10_000, 20_000, 30_000]);
  assert.equal(asset.fitsBuildVolume, true);
});

test("parses a quote request with a null latest analysis", async () => {
  const list = await fetchQuoteRequestList(baseQuoteRequestPayload(null));
  assert.equal(list.items[0]!.latestAnalysis, null);
});

test("rejects a latest analysis run with an invalid status", async () => {
  const invalidRun = { ...validAnalysisRunPayload() as Record<string, unknown>, status: "bogus" };
  await assert.rejects(
    () => fetchQuoteRequestList(baseQuoteRequestPayload(invalidRun)),
    (error: unknown) => error instanceof QuoteApiError && error.status === 502,
  );
});

test("rejects a latest analysis asset with malformed dimensions", async () => {
  const invalidAsset = {
    ...validAnalysisAssetResultPayload() as Record<string, unknown>,
    dimensionsUm: [10_000, 20_000],
  };
  const invalidRun = {
    ...validAnalysisRunPayload() as Record<string, unknown>,
    assets: [invalidAsset],
  };
  await assert.rejects(
    () => fetchQuoteRequestList(baseQuoteRequestPayload(invalidRun)),
    (error: unknown) => error instanceof QuoteApiError && error.status === 502,
  );
});

test("rejects a latest analysis asset with a malformed digest shape", async () => {
  const invalidAsset = {
    ...validAnalysisAssetResultPayload() as Record<string, unknown>,
    verifiedSha256: "not-a-lowercase-hex-digest",
  };
  const invalidRun = {
    ...validAnalysisRunPayload() as Record<string, unknown>,
    assets: [invalidAsset],
  };
  await assert.rejects(
    () => fetchQuoteRequestList(baseQuoteRequestPayload(invalidRun)),
    (error: unknown) => error instanceof QuoteApiError && error.status === 502,
  );
});

test("rejects a latest analysis run with a malformed profile digest shape", async () => {
  const invalidRun = {
    ...validAnalysisRunPayload() as Record<string, unknown>,
    profileSha256: "ABCDEF",
  };
  await assert.rejects(
    () => fetchQuoteRequestList(baseQuoteRequestPayload(invalidRun)),
    (error: unknown) => error instanceof QuoteApiError && error.status === 502,
  );
});

test("rejects a latest analysis run with a non-UUID id", async () => {
  const invalidRun = {
    ...validAnalysisRunPayload() as Record<string, unknown>,
    id: "not-a-uuid",
  };
  await assert.rejects(
    () => fetchQuoteRequestList(baseQuoteRequestPayload(invalidRun)),
    (error: unknown) => error instanceof QuoteApiError && error.status === 502,
  );
});

test("rejects a latest analysis asset with a non-UUID assetId", async () => {
  const invalidAsset = {
    ...validAnalysisAssetResultPayload() as Record<string, unknown>,
    assetId: "00000000-0000-0000-0000-00000000001",
  };
  const invalidRun = {
    ...validAnalysisRunPayload() as Record<string, unknown>,
    assets: [invalidAsset],
  };
  await assert.rejects(
    () => fetchQuoteRequestList(baseQuoteRequestPayload(invalidRun)),
    (error: unknown) => error instanceof QuoteApiError && error.status === 502,
  );
});

test("rejects a latest analysis run with an impossible calendar timestamp", async () => {
  const invalidRun = {
    ...validAnalysisRunPayload() as Record<string, unknown>,
    queuedAt: "2026-02-30T00:00:00Z",
  };
  await assert.rejects(
    () => fetchQuoteRequestList(baseQuoteRequestPayload(invalidRun)),
    (error: unknown) => error instanceof QuoteApiError && error.status === 502,
  );
});

test("rejects a latest analysis run with an out-of-range clock timestamp", async () => {
  const invalidRun = {
    ...validAnalysisRunPayload() as Record<string, unknown>,
    startedAt: "2026-01-01T24:00:00Z",
  };
  await assert.rejects(
    () => fetchQuoteRequestList(baseQuoteRequestPayload(invalidRun)),
    (error: unknown) => error instanceof QuoteApiError && error.status === 502,
  );
});

test("accepts a latest analysis run timestamp with a numeric UTC offset", async () => {
  const validRun = {
    ...validAnalysisRunPayload() as Record<string, unknown>,
    queuedAt: "2026-01-01T05:30:00+05:30",
  };
  const list = await fetchQuoteRequestList(baseQuoteRequestPayload(validRun));
  assert.equal(list.items[0]!.latestAnalysis?.queuedAt, "2026-01-01T05:30:00+05:30");
});

test("rejects a latest analysis run timestamp with an out-of-range UTC offset", async () => {
  const invalidRun = {
    ...validAnalysisRunPayload() as Record<string, unknown>,
    queuedAt: "2026-01-01T00:00:00+24:00",
  };
  await assert.rejects(
    () => fetchQuoteRequestList(baseQuoteRequestPayload(invalidRun)),
    (error: unknown) => error instanceof QuoteApiError && error.status === 502,
  );
});
