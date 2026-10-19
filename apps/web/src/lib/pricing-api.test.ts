import assert from "node:assert/strict";
import test from "node:test";

import {
  PricingApiError,
  activatePricingPolicy,
  createPricingPolicy,
  listPricingPolicies,
} from "./pricing-api.ts";

function validPolicy() {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    version: 1,
    status: "draft",
    currency: "INR",
    machineRatePaisePerHour: 10_000,
    setupFeePaise: 1_000,
    minimumOrderPaise: 10_000,
    contingencyBps: 1_000,
    taxBps: 0,
    estimateValidityHours: 48,
    materials: [{
      id: "00000000-0000-0000-0000-000000000002",
      code: "pla",
      displayName: "PLA",
      ratePaisePerGram: 200,
    }],
    activatedAt: null,
    createdAt: "2026-07-17T00:00:00Z",
  };
}

test("parses an owner pricing policy list", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ items: [validPolicy()] });
  try {
    const policies = await listPricingPolicies();
    assert.equal(policies[0]?.materials[0]?.code, "pla");
    assert.equal(policies[0]?.machineRatePaisePerHour, 10_000);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("sends draft values as integer paise with the session CSRF proof", async () => {
  const originalFetch = globalThis.fetch;
  let captured: RequestInit | undefined;
  globalThis.fetch = async (_input, init) => {
    captured = init;
    return Response.json(validPolicy(), { status: 201 });
  };
  try {
    await createPricingPolicy({
      machineRatePaisePerHour: 10_000,
      setupFeePaise: 1_000,
      minimumOrderPaise: 10_000,
      contingencyBps: 1_000,
      taxBps: 0,
      estimateValidityHours: 48,
      materials: [{ code: "pla", displayName: "PLA", ratePaisePerGram: 200 }],
    }, "xxx_csrf=signed%3Atoken");
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(new Headers(captured?.headers).get("x-csrf-token"), "signed:token");
  assert.equal(JSON.parse(String(captured?.body)).machineRatePaisePerHour, 10_000);
});

test("refuses activation without a signed CSRF cookie", async () => {
  await assert.rejects(
    () => activatePricingPolicy("policy", "unrelated=value"),
    (error: unknown) => error instanceof PricingApiError && error.status === 401,
  );
});
