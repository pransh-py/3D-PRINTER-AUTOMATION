import assert from "node:assert/strict";
import test from "node:test";
import { buyerNextSteps, type BuyerDashboard } from "./dashboard-api.ts";
import type { PrintPreset } from "./print-specification.ts";
import type { OrderDetail, PrintJob } from "./workflow-api.ts";
import {
  firstInvalidStep,
  canRecoverDispatch,
  jobGroup,
  matchesOrder,
  matchesRequest,
  nextJob,
  orderGroup,
  orderNextAction,
  orderProgress,
  quotationState,
  requestTriage,
  statusPresentation,
  validateQuoteStep,
  type QuoteDraft,
} from "./order-journey.ts";

test("only expired or revoked unclaimed authorizations expose safe readiness recovery", () => {
  const now = Date.parse("2026-10-21T01:00:00Z");
  const grant = { id: "fixture", claimedAt: null, revokedAt: null, expiresAt: "2026-10-21T01:01:00Z" };
  assert.equal(canRecoverDispatch("authorized", grant, now), false);
  assert.equal(canRecoverDispatch("authorized", { ...grant, expiresAt: "2026-10-21T00:59:00Z" }, now), true);
  assert.equal(canRecoverDispatch("authorized", { ...grant, revokedAt: "2026-10-21T00:59:00Z" }, now), true);
  assert.equal(canRecoverDispatch("authorized", { ...grant, claimedAt: "2026-10-21T00:59:00Z", revokedAt: "2026-10-21T00:59:01Z" }, now), false);
  for (const status of ["claimed", "printing", "preparing", "completed"])
    assert.equal(canRecoverDispatch(status, { ...grant, revokedAt: "2026-10-21T00:59:00Z" }, now), false);
  assert.equal(canRecoverDispatch("authorized", null, now), false);
});

const preset: PrintPreset = {
  code: "pla",
  label: "Standard",
  materialCode: "pla",
  profileSha256: "a".repeat(64),
  colours: ["Red", "White", "Black"],
  settings: {
    nozzleDiameterMm: "0.4",
    layerHeightMm: "0.2",
    infillPercent: 20,
    supports: false,
    wallLoops: 3,
    filamentType: "PLA",
  },
};
const draft: QuoteDraft = {
  fileCount: 1,
  selectionErrors: [],
  preset,
  colour: "White",
  quantity: "1",
  fulfillmentMode: "pickup",
  notes: "",
};
const statuses = [
  "payment_pending",
  "payment_processing",
  "payment_failed",
  "payment_review",
  "paid_confirmed",
  "queued",
  "preparing",
  "ready_to_print",
  "printing",
  "qa",
  "on_hold",
  "print_failed",
  "ready_for_pickup",
  "out_for_delivery",
  "shipped",
  "completed",
];

test("all known states have readable labels and unknown states stay neutral", () => {
  const byKind = {
    order: statuses,
    job: [
      "queued",
      "preparing",
      "ready_to_print",
      "authorized",
      "claimed",
      "printing",
      "qa",
      "on_hold",
      "failed",
      "completed",
      "cancelled",
    ],
    quotation: ["issued", "accepted", "superseded", "rejected", "expired"],
    request: [
      "draft",
      "analyzing",
      "analysis_ready",
      "estimate_ready",
      "owner_review",
      "quoted",
      "analysis_failed",
      "rejected",
    ],
    fulfillment: [
      "pending",
      "ready_for_pickup",
      "out_for_delivery",
      "shipped",
      "completed",
    ],
  } as const;
  for (const [kind, values] of Object.entries(byKind))
    for (const status of values) {
      const p = statusPresentation(kind as keyof typeof byKind, status);
      assert.ok(p.label.length > 0 && !p.label.includes("_"));
      assert.ok(
        ["neutral", "action", "progress", "success", "attention"].includes(
          p.tone,
        ),
      );
    }
  assert.deepEqual(statusPresentation("order", "future_state"), {
    label: "Future state",
    tone: "neutral",
  });
  assert.deepEqual(statusPresentation("order", "issued"), {
    label: "Issued",
    tone: "neutral",
  });
});

test("order filters agree with dashboard counts for every backend order state", () => {
  const fields = {
    payment_due: "paymentDue",
    payment_processing: "paymentProcessing",
    production: "production",
    attention: "needsAttention",
    handover: "handover",
    completed: "completed",
  } as const;
  for (const status of statuses) {
    const data: BuyerDashboard = {
      generatedAt: "2026-10-21T00:00:00Z",
      quoteRequests: {},
      openQuotations: 0,
      orders: { [status]: 1 },
      payments: { onlineEnabled: false, testMode: false },
    };
    const group = orderGroup(status);
    assert.notEqual(group, "other");
    assert.equal(buyerNextSteps(data)[fields[group as keyof typeof fields]], 1);
  }
  assert.equal(orderGroup("future"), "other");
});

test("progress never invents a current stage for unknown state and flags exceptions", () => {
  const expected = [1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 2, 2, 4, 4, 4, 5];
  statuses.forEach((status, i) =>
    assert.equal(orderProgress(status, "pickup").current, expected[i]),
  );
  for (const status of [
    "payment_failed",
    "payment_review",
    "on_hold",
    "print_failed",
  ])
    assert.equal(orderProgress(status, "pickup").flagged, true);
  assert.equal(orderProgress("future", "shipping").current, null);
  assert.equal(orderProgress("shipped", "shipping").steps[4], "Shipped");
  assert.equal(
    orderProgress("out_for_delivery", "local_delivery").steps[4],
    "Out for delivery",
  );
});

test("pay action requires a buyer, enabled checkout and a payable server status", () => {
  for (const viewer of ["buyer", "owner"] as const)
    for (const checkoutEnabled of [true, false])
      for (const status of [...statuses, "future"]) {
        const order = {
          status,
          payment: {
            checkoutEnabled,
            testMode: true,
            message: "Server message",
          },
        } as OrderDetail;
        assert.equal(
          orderNextAction(order, viewer).code === "pay",
          viewer === "buyer" &&
            checkoutEnabled &&
            ["payment_pending", "payment_failed"].includes(status),
        );
        if (["payment_processing", "payment_review"].includes(status))
          assert.match(
            orderNextAction(order, viewer).message,
            /do not pay again/i,
          );
        if (
          !checkoutEnabled &&
          ["payment_pending", "payment_failed"].includes(status)
        )
          assert.equal(
            orderNextAction(order, viewer).message,
            "Server message",
          );
      }
});

test("quotation expiry is clock-derived and accepted quotations remain accepted", () => {
  const q = { status: "issued", expiresAt: "2026-10-21T12:00:00Z" };
  assert.equal(
    quotationState(q, Date.parse("2026-10-21T11:59:59Z")),
    "actionable",
  );
  assert.equal(quotationState(q, Date.parse(q.expiresAt)), "expired");
  assert.equal(
    quotationState({ ...q, status: "accepted" }, Infinity),
    "accepted",
  );
  assert.equal(quotationState({ ...q, status: "superseded" }, 0), "closed");
});

test("request triage prioritizes profile failures and accepted quotes cannot be quoted again", () => {
  for (const status of ["analysis_ready", "estimate_ready", "owner_review"])
    assert.equal(requestTriage({ status }), "to_quote");
  assert.notEqual(
    requestTriage({ status: "owner_review" }, "accepted"),
    "to_quote",
  );
  assert.equal(
    requestTriage({
      status: "analyzing",
      latestAnalysis: { status: "awaiting_profile" },
    }),
    "attention",
  );
  assert.equal(
    requestTriage({
      status: "analyzing",
      latestAnalysis: { status: "failed", failureCode: "slicer_failed" },
    }),
    "attention",
  );
  assert.equal(requestTriage({ status: "analysis_failed" }), "attention");
  assert.equal(requestTriage({ status: "draft" }), "processing");
  assert.equal(requestTriage({ status: "quoted" }), "quoted");
  assert.equal(requestTriage({ status: "rejected" }), "rejected");
});

test("search only considers references, request prefixes and filenames", () => {
  assert.equal(matchesOrder({ publicReference: "PF-ABCD" }, " abC "), true);
  assert.equal(matchesOrder({ publicReference: "PF-ABCD" }, "absent"), false);
  const request = {
    id: "12345678-abcd",
    assets: [{ filename: "Bracket.STL" }],
    buyerNotes: "secret",
  };
  assert.equal(matchesRequest(request, " bracket "), true);
  assert.equal(matchesRequest(request, "1234"), true);
  assert.equal(matchesRequest(request, "abcd"), false);
  assert.equal(matchesRequest(request, "secret"), false);
  assert.equal(matchesRequest(request, ""), true);
});

test("next job respects queue rank and ignores QA, held, failed and completed work", () => {
  const jobs = [
    { id: "b", status: "queued", queueRank: 2 },
    { id: "a", status: "preparing", queueRank: 1 },
    { id: "c", status: "on_hold", queueRank: 0 },
  ] as PrintJob[];
  assert.equal(nextJob(jobs)?.id, "a");
  assert.equal(nextJob([]), null);
  for (const status of ["qa", "on_hold", "failed", "completed", "cancelled"])
    assert.equal(
      nextJob([{ id: "z", status, queueRank: 0 }] as PrintJob[]),
      null,
    );
  assert.equal(jobGroup("failed"), "attention");
  assert.equal(jobGroup("qa"), "active");
  assert.equal(jobGroup("cancelled"), "completed");
});

test("wizard boundaries block invalid data and allow exact backend limits", () => {
  assert.equal(firstInvalidStep(draft), null);
  assert.equal(validateQuoteStep(0, draft), null);
  for (const fileCount of [0, 6])
    assert.equal(firstInvalidStep({ ...draft, fileCount }), 0);
  assert.equal(
    firstInvalidStep({ ...draft, selectionErrors: ["Bad file"] }),
    0,
  );
  assert.equal(firstInvalidStep({ ...draft, preset: undefined }), 1);
  assert.equal(firstInvalidStep({ ...draft, colour: "Blue" }), 1);
  for (const quantity of ["", "0", "101", "1.5", "1e2", "-1", " 1"])
    assert.equal(firstInvalidStep({ ...draft, quantity }), 1);
  for (const quantity of ["1", "100"])
    assert.equal(firstInvalidStep({ ...draft, quantity }), null);
  assert.equal(firstInvalidStep({ ...draft, fulfillmentMode: "teleport" }), 2);
  assert.equal(firstInvalidStep({ ...draft, notes: "x".repeat(1001) }), 2);
  assert.equal(firstInvalidStep({ ...draft, notes: "x".repeat(1000) }), null);
});
