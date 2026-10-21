import type { PrintPreset } from "./print-specification.ts";
import type { OrderDetail, PrintJob, StationDispatch } from "./workflow-api.ts";

export function canRecoverDispatch(
  status: string,
  grant: StationDispatch["authorization"] | undefined,
  now: number,
): boolean {
  return status === "authorized" && !!grant && grant.claimedAt === null
    && (grant.revokedAt !== null || Date.parse(grant.expiresAt) <= now);
}

export type StatusKind =
  "order" | "job" | "quotation" | "request" | "fulfillment";
export type Tone = "neutral" | "action" | "progress" | "success" | "attention";
export type OrderGroup =
  | "payment_due"
  | "payment_processing"
  | "production"
  | "attention"
  | "handover"
  | "completed"
  | "other";
export type RequestTriage =
  "attention" | "to_quote" | "processing" | "quoted" | "rejected" | "other";
const labels: Record<string, string> = {
  payment_pending: "Payment due",
  payment_processing: "Confirming payment",
  payment_failed: "Payment unsuccessful",
  payment_review: "Payment needs review",
  paid_confirmed: "Payment confirmed",
  queued: "In the print queue",
  preparing: "Preparing your print",
  ready_to_print: "Ready to print",
  authorized: "Waiting for station",
  claimed: "Preparing to print",
  printing: "Printing",
  qa: "Quality check",
  on_hold: "On hold",
  print_failed: "Print needs attention",
  failed: "Failed",
  ready_for_pickup: "Ready for pickup",
  out_for_delivery: "Out for delivery",
  shipped: "Shipped",
  completed: "Completed",
  cancelled: "Cancelled",
  issued: "Ready to review",
  accepted: "Accepted",
  superseded: "Replaced",
  rejected: "Declined",
  expired: "Expired",
  draft: "Draft",
  analyzing: "Checking your models",
  analysis_ready: "Analysis ready",
  estimate_ready: "Ready for quotation",
  owner_review: "Owner review",
  quoted: "Quotation issued",
  analysis_failed: "Model needs attention",
  pending: "Pending",
};

const known: Record<StatusKind, readonly string[]> = {
  order: [
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
  ],
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
};

export function statusPresentation(
  kind: StatusKind,
  status: string,
): { label: string; tone: Tone } {
  if (!known[kind].includes(status))
    return {
      label: status.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase()),
      tone: "neutral",
    };
  const label =
    labels[status] ??
    status.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
  let tone: Tone = "neutral";
  if (
    [
      "payment_failed",
      "payment_review",
      "on_hold",
      "print_failed",
      "failed",
      "analysis_failed",
      "rejected",
    ].includes(status)
  )
    tone = "attention";
  else if (["completed", "accepted"].includes(status)) tone = "success";
  else if (
    [
      "payment_pending",
      "issued",
      "estimate_ready",
      "owner_review",
      "analysis_ready",
      "ready_for_pickup",
    ].includes(status)
  )
    tone = "action";
  else if (
    [
      "payment_processing",
      "paid_confirmed",
      "queued",
      "preparing",
      "ready_to_print",
      "authorized",
      "claimed",
      "printing",
      "qa",
      "analyzing",
      "shipped",
      "out_for_delivery",
    ].includes(status)
  )
    tone = "progress";
  if (kind === "fulfillment" && status === "pending")
    return { label: "Awaiting handover", tone: "neutral" };
  return { label, tone };
}

export function orderGroup(status: string): OrderGroup {
  if (["payment_pending", "payment_failed"].includes(status))
    return "payment_due";
  if (status === "payment_processing") return "payment_processing";
  if (
    [
      "paid_confirmed",
      "queued",
      "preparing",
      "ready_to_print",
      "printing",
      "qa",
    ].includes(status)
  )
    return "production";
  if (["on_hold", "print_failed", "payment_review"].includes(status))
    return "attention";
  if (["ready_for_pickup", "out_for_delivery", "shipped"].includes(status))
    return "handover";
  return status === "completed" ? "completed" : "other";
}

export function orderProgress(status: string, mode: string = "pickup") {
  const steps = [
    "Accepted",
    "Payment confirmed",
    "In production",
    "Quality check",
    (
      {
        pickup: "Ready for pickup",
        local_delivery: "Out for delivery",
        shipping: "Shipped",
      } as Record<string, string>
    )[mode] ?? "Handover",
    "Completed",
  ];
  const group = orderGroup(status);
  const current =
    group === "other"
      ? null
      : status === "completed"
        ? 5
        : group === "handover"
          ? 4
          : status === "qa"
            ? 3
            : ["payment_due", "payment_processing"].includes(group) ||
                status === "payment_review"
              ? 1
              : 2;
  return {
    steps,
    current,
    flagged: [
      "payment_failed",
      "payment_review",
      "on_hold",
      "print_failed",
    ].includes(status),
  };
}

type NextAction = {
  code:
    | "pay"
    | "wait"
    | "review"
    | "production"
    | "handover"
    | "complete"
    | "unavailable"
    | "unknown";
  title: string;
  message: string;
};
export function orderNextAction(
  order: Pick<OrderDetail, "status" | "payment">,
  viewer: "buyer" | "owner",
): NextAction {
  const group = orderGroup(order.status);
  if (group === "payment_due") {
    if (!order.payment.checkoutEnabled)
      return {
        code: "unavailable",
        title: "Payment is not available yet",
        message: order.payment.message,
      };
    if (viewer === "buyer")
      return {
        code: "pay",
        title: order.payment.testMode
          ? "Continue to test payment"
          : "Complete your payment",
        message:
          "Your quotation is accepted. Production starts once payment is confirmed.",
      };
    return {
      code: "wait",
      title: "Awaiting buyer payment",
      message:
        "The buyer can pay from their order page.",
    };
  }
  if (["payment_processing", "payment_review"].includes(order.status))
    return {
      code: "review",
      title: "Payment confirmation in progress",
      message:
        "Payment is being confirmed. Do not pay again while this is in progress.",
    };
  if (["on_hold", "print_failed"].includes(order.status))
    return {
      code: "review",
      title: "This print needs attention",
      message:
        viewer === "owner"
          ? "Review the production job and operator notes before continuing."
          : "We’re reviewing this print. Check the history below for updates.",
    };
  if (group === "production")
    return {
      code: "production",
      title:
        order.status === "qa"
          ? "Quality check before handover"
          : "Your order is in production",
      message:
        viewer === "owner"
          ? order.status === "qa"
            ? "Verify quality checks in the order history. Record fulfilment below only after QA has passed."
            : "Use the production queue for preparation, readiness, printing and quality checks."
          : "Every part is quality-checked before handover.",
    };
  if (group === "handover")
    return {
      code: "handover",
      title: statusPresentation("order", order.status).label,
      message:
        "Pickup, delivery or shipping details are below.",
    };
  if (group === "completed")
    return {
      code: "complete",
      title: "Order completed",
      message:
        "Marked as collected or received. Order details remain below.",
    };
  return {
    code: "unknown",
    title: "Order status update",
    message:
      "Check the status and history below.",
  };
}

export function quotationState(
  q: { status: string; expiresAt: string },
  now: number,
): "actionable" | "accepted" | "expired" | "closed" {
  if (q.status === "accepted") return "accepted";
  if (q.status !== "issued") return "closed";
  const expiry = Date.parse(q.expiresAt);
  return Number.isFinite(expiry) && expiry > now ? "actionable" : "expired";
}

export function requestTriage(
  request: {
    status: string;
    latestAnalysis?: { status: string; failureCode?: string | null } | null;
  },
  finalQuoteStatus?: string,
): RequestTriage {
  if (
    request.status === "analysis_failed" ||
    request.latestAnalysis?.status === "awaiting_profile" ||
    request.latestAnalysis?.failureCode?.startsWith("slicer_")
  )
    return "attention";
  if (
    ["analysis_ready", "estimate_ready", "owner_review"].includes(
      request.status,
    ) &&
    finalQuoteStatus !== "accepted"
  )
    return "to_quote";
  if (["draft", "analyzing"].includes(request.status)) return "processing";
  if (request.status === "quoted" || finalQuoteStatus === "accepted")
    return "quoted";
  return request.status === "rejected" ? "rejected" : "other";
}
export function matchesOrder(
  order: { publicReference: string },
  search: string,
): boolean {
  return order.publicReference
    .toLowerCase()
    .includes(search.trim().toLowerCase());
}
export function matchesRequest(
  request: { id: string; assets: readonly { filename: string }[] },
  search: string,
): boolean {
  const query = search.trim().toLowerCase();
  return (
    !query ||
    request.id.toLowerCase().startsWith(query) ||
    request.assets.some((asset) => asset.filename.toLowerCase().includes(query))
  );
}
export function jobGroup(
  status: string,
): "active" | "attention" | "completed" | "other" {
  if (
    [
      "queued",
      "preparing",
      "ready_to_print",
      "authorized",
      "claimed",
      "printing",
      "qa",
    ].includes(status)
  )
    return "active";
  if (["on_hold", "failed"].includes(status)) return "attention";
  return ["completed", "cancelled"].includes(status) ? "completed" : "other";
}
export function nextJob(jobs: readonly PrintJob[]): PrintJob | null {
  return (
    jobs
      .filter((job) =>
        [
          "queued",
          "preparing",
          "ready_to_print",
          "authorized",
          "claimed",
          "printing",
        ].includes(job.status),
      )
      .sort(
        (a, b) =>
          (a.queueRank ?? Infinity) - (b.queueRank ?? Infinity) ||
          a.id.localeCompare(b.id),
      )[0] ?? null
  );
}

export type QuoteDraft = Readonly<{
  fileCount: number;
  selectionErrors: readonly string[];
  preset?: PrintPreset;
  colour: string;
  quantity: string;
  fulfillmentMode: string;
  notes: string;
}>;
export function validateQuoteStep(
  step: number,
  draft: QuoteDraft,
): string | null {
  if (step === 0)
    return draft.fileCount < 1 ||
      draft.fileCount > 5 ||
      draft.selectionErrors.length
      ? "Choose between 1 and 5 supported model files before continuing."
      : null;
  if (step === 1) {
    if (!draft.preset)
      return "Choose an available print profile. Ordering opens when the owner configures the catalogue.";
    if (
      draft.preset.colours.length &&
      !draft.preset.colours.includes(draft.colour)
    )
      return "Choose a colour offered for this print profile.";
    if (
      !/^\d+$/.test(draft.quantity) ||
      Number(draft.quantity) < 1 ||
      Number(draft.quantity) > 100
    )
      return "Enter a whole number of copies between 1 and 100.";
  }
  if (step === 2) {
    if (
      !["pickup", "local_delivery", "shipping"].includes(draft.fulfillmentMode)
    )
      return "Choose pickup, local delivery or shipping.";
    if (draft.notes.length > 1000)
      return "Keep requirements to 1000 characters or fewer.";
  }
  return null;
}
export function firstInvalidStep(draft: QuoteDraft): number | null {
  for (let step = 0; step < 3; step++)
    if (validateQuoteStep(step, draft)) return step;
  return null;
}
