import assert from "node:assert/strict";
import test from "node:test";
import { AuthApiError } from "./auth-api.ts";
import {
  buyerNextSteps,
  getBuyerDashboard,
  getOwnerDashboard,
  ownerAttention,
  parseBuyerDashboard,
  parseOwnerDashboard,
  roleHome,
  resolveDashboardAccess,
  totalStates,
} from "./dashboard-api.ts";

test("dashboard access follows verified roles and redirects only known sessions", () => {
  assert.deepEqual(resolveDashboardAccess("buyer", "buyer"), { kind: "allow" });
  assert.deepEqual(resolveDashboardAccess("owner", "owner"), { kind: "allow" });
  assert.deepEqual(resolveDashboardAccess("owner", "buyer"), { kind: "redirect", href: "/orders" });
  assert.deepEqual(resolveDashboardAccess("buyer", "owner"), { kind: "redirect", href: "/operations" });
  assert.deepEqual(resolveDashboardAccess("buyer", new AuthApiError("Expired", 401)), { kind: "redirect", href: "/sign-in" });
  for (const status of [0, 403, 429, 500, 502]) {
    assert.deepEqual(resolveDashboardAccess("buyer", new AuthApiError("Unavailable", status)), { kind: "unavailable" });
  }
  assert.deepEqual(resolveDashboardAccess("owner", new TypeError("Offline")), { kind: "unavailable" });
  assert.deepEqual(resolveDashboardAccess("buyer", { status: 401 }), { kind: "unavailable" });
});

const buyer = {
  generatedAt: "2026-10-21T00:00:00Z",
  quoteRequests: { draft: 2 },
  openQuotations: 1,
  orders: {
    payment_pending: 3,
    payment_processing: 1,
    printing: 2,
    completed: 4,
  },
  payments: { onlineEnabled: false, testMode: false },
};
const owner = {
  ...buyer,
  quoteRequests: { estimate_ready: 2, owner_review: 3, analysis_failed: 1 },
  orders: { payment_review: 2, shipped: 1 },
  payments: { captured: 4 },
  fulfillments: { pending: 1 },
  printJobs: { queued: 4, printing: 1, failed: 2, on_hold: 1, completed: 7 },
  notifications: { enabled: false, counts: { failed: 2, dead_lettered: 1 } },
  setup: {
    ownerMfaEnabled: true,
    pricingPolicyActive: true,
    onlinePaymentsEnabled: false,
    paymentsTestMode: false,
  },
};

test("dashboard summaries validate counts and optional future status keys", () => {
  assert.deepEqual(parseBuyerDashboard(buyer), buyer);
  assert.deepEqual(parseOwnerDashboard(owner), owner);
  assert.equal(
    parseBuyerDashboard({ ...buyer, orders: { future_state: 5 } }).orders
      .future_state,
    5,
  );
  for (const value of [
    -1,
    1.5,
    "2",
    NaN,
    Infinity,
    Number.MAX_SAFE_INTEGER + 1,
  ]) {
    assert.throws(() =>
      parseBuyerDashboard({ ...buyer, orders: { queued: value } }),
    );
  }
  for (const value of [
    null,
    [],
    {},
    { ...owner, setup: undefined },
    { ...owner, notifications: { enabled: "true", counts: {} } },
  ]) {
    assert.throws(() => parseOwnerDashboard(value));
  }
  assert.throws(() =>
    parseBuyerDashboard({
      ...buyer,
      payments: { onlineEnabled: false, testMode: true },
    }),
  );
});

test("role homes and next steps do not mix pending payments with processing or completed jobs", () => {
  assert.equal(roleHome("owner"), "/operations");
  assert.equal(roleHome("buyer"), "/orders");
  assert.deepEqual(buyerNextSteps(buyer), {
    drafts: 2,
    awaitingOwner: 0,
    analysisFailed: 0,
    quotations: 1,
    paymentDue: 3,
    paymentProcessing: 1,
    production: 2,
    needsAttention: 0,
    handover: 0,
    completed: 4,
  });
  assert.deepEqual(ownerAttention(owner), {
    readyToQuote: 5,
    analysisFailed: 1,
    paymentReview: 2,
    activeProduction: 5,
    flaggedJobs: 3,
    handover: 1,
    notificationFailures: 3,
  });
  assert.equal(totalStates({}), 0);
  assert.equal(totalStates({ first: 100, future: 25 }), 125);
});

test("role-specific summary requests use the existing authenticated no-store transport", async () => {
  const original = globalThis.fetch;
  const paths: string[] = [];
  globalThis.fetch = async (input, init) => {
    paths.push(String(input));
    assert.equal(init?.credentials, "same-origin");
    assert.equal(init?.cache, "no-store");
    return Response.json(String(input).includes("/owner/") ? owner : buyer);
  };
  try {
    await getBuyerDashboard();
    await getOwnerDashboard();
  } finally {
    globalThis.fetch = original;
  }
  assert.deepEqual(paths, [
    "/api/v1/buyer/dashboard",
    "/api/v1/owner/dashboard",
  ]);
});
