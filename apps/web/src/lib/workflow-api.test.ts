import test from "node:test";
import assert from "node:assert/strict";
import {
  parseRupees,
  acceptQuotation,
  getOrder,
  getArtifacts,
  listOrders,
  createCheckout,
  reconcilePayment,
  listNotifications,
} from "./workflow-api.ts";

test("rupees convert exactly to paise without fractional money", () => {
  assert.equal(parseRupees("12.01"), 1201);
  assert.equal(parseRupees("0.1"), 10);
  assert.equal(parseRupees("-12.01", true), -1201);
  for (const value of ["1.001", "NaN", "1e3", "", "-2", "1000000000000000"])
    assert.throws(() => parseRupees(value));
});

test("notification records require exact state, attempt and timestamp types", async () => {
  const originalFetch = globalThis.fetch;
  const row = { id, templateCode: "buyer.quote_issued", status: "sent", attemptCount: 1,
    lastErrorCode: null, createdAt: "2026-10-11T00:00:00Z",
    availableAt: "2026-10-11T00:00:00Z", sentAt: "2026-10-11T00:00:00Z" };
  try {
    globalThis.fetch = async () => Response.json({ enabled: false, items: [row] });
    assert.equal((await listNotifications()).items[0].status, "sent");
    for (const change of [{ status: "paid" }, { attemptCount: -1 }, { sentAt: "yesterday" }]) {
      globalThis.fetch = async () => Response.json({ enabled: true, items: [{ ...row, ...change }] });
      await assert.rejects(listNotifications(), /invalid record/);
    }
  } finally { globalThis.fetch = originalFetch; }
});

const id = "11111111-1111-4111-8111-111111111111";
const order = {
  id,
  publicReference: "LAB ONLY",
  acceptedQuoteId: id,
  status: "payment_pending",
  version: 1,
  currency: "INR",
  amountPaise: 100,
  acceptedAt: "2026-10-05T00:00:00Z",
  completedAt: null,
};

test("acceptance sends session CSRF proof and never client-supplied prices", async () => {
  const originalFetch = globalThis.fetch;
  const originalDocument = Object.getOwnPropertyDescriptor(
    globalThis,
    "document",
  );
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: { cookie: "xxx_csrf=fixture" },
  });
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(url, `/api/v1/quotations/${id}/accept`);
      assert.equal(options?.credentials, "same-origin");
      assert.equal(options?.cache, "no-store");
      assert.equal(
        new Headers(options?.headers).get("X-CSRF-Token"),
        "fixture",
      );
      assert.deepEqual(JSON.parse(String(options?.body)), { address: null });
      return Response.json(order);
    };
    assert.equal((await acceptQuotation(id)).amountPaise, 100);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalDocument)
      Object.defineProperty(globalThis, "document", originalDocument);
    else Reflect.deleteProperty(globalThis, "document");
  }
});

test("order details preserve the accepted private destination and reject malformed addresses", async () => {
  const originalFetch = globalThis.fetch;
  const fulfillment = {
    mode: "shipping",
    status: "pending",
    chargePaise: 0,
    carrierName: null,
    trackingReference: null,
    dispatchedAt: null,
    completedAt: null,
    destination: {
      recipientName: "LAB ONLY",
      phoneE164: "+919000000000",
      line1: "Fictional test address",
      line2: "",
      locality: "Test",
      district: "Test",
      state: "Tamil Nadu",
      postalCode: "600001",
      countryCode: "IN",
    },
  };
  const detail = {
    ...order,
    lines: [],
    timeline: [],
    fulfillment,
    payment: { checkoutEnabled: false, testMode: false, message: "Deferred" },
  };
  try {
    globalThis.fetch = async () => Response.json(detail);
    assert.equal(
      (await getOrder(id)).fulfillment?.destination?.recipientName,
      "LAB ONLY",
    );
    globalThis.fetch = async () =>
      Response.json({
        ...detail,
        fulfillment: {
          ...fulfillment,
          destination: { ...fulfillment.destination, phoneE164: "unvalidated" },
        },
      });
    await assert.rejects(getOrder(id), /invalid record/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rejects fractional money, malformed timeline and unscoped artifact downloads", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () =>
      Response.json({ items: [{ ...order, amountPaise: 1.5 }] });
    await assert.rejects(listOrders(), /invalid record/);
    globalThis.fetch = async () =>
      Response.json({
        ...order,
        lines: [],
        fulfillment: null,
        timeline: [
          { event: "print_completed", at: "not-a-date", progressBps: null },
        ],
        payment: {
          checkoutEnabled: false,
          testMode: false,
          message: "Deferred",
        },
      });
    await assert.rejects(getOrder(id), /invalid record/);
    globalThis.fetch = async () =>
      Response.json({
        items: [
          {
            id,
            sha256: "a".repeat(64),
            position: 1,
            quantity: 1,
            downloadUrl: "https://another-host.example/private-file",
          },
        ],
      });
    await assert.rejects(getArtifacts(id), /invalid record/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Checkout requests contain no client amount and validate mode and exact money", async () => {
  const originalFetch = globalThis.fetch;
  const originalDocument = Object.getOwnPropertyDescriptor(
    globalThis,
    "document",
  );
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: { cookie: "xxx_csrf=fixture" },
  });
  const checkout = {
    intentId: id,
    keyId: "rzp_test_Fictional",
    displayName: "FICTIONAL TEST STORE",
    providerOrderId: "order_Fictional",
    amountPaise: 100,
    currency: "INR",
    testMode: true,
  };
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(url, `/api/v1/orders/${id}/checkout`);
      assert.deepEqual(JSON.parse(String(options?.body)), {});
      assert.equal(options?.credentials, "same-origin");
      assert.equal(
        new Headers(options?.headers).get("X-CSRF-Token"),
        "fixture",
      );
      return Response.json(checkout);
    };
    assert.equal((await createCheckout(id)).amountPaise, 100);
    for (const change of [
      { amountPaise: 1.5 },
      { currency: "USD" },
      { testMode: false },
      { keyId: "https://attacker.example" },
    ]) {
      globalThis.fetch = async () => Response.json({ ...checkout, ...change });
      await assert.rejects(createCheckout(id), /invalid record/);
    }
    globalThis.fetch = async (url, options) => {
      assert.equal(url, `/api/v1/owner/orders/${id}/reconcile`);
      assert.deepEqual(JSON.parse(String(options?.body)), {});
      return Response.json({ ...order, status: "payment_processing" });
    };
    assert.equal(
      (await reconcilePayment(id, true)).status,
      "payment_processing",
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (originalDocument)
      Object.defineProperty(globalThis, "document", originalDocument);
    else Reflect.deleteProperty(globalThis, "document");
  }
});
