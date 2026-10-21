import { AuthApiError } from "./auth-api.ts";
import { request, WorkflowApiError } from "./workflow-api.ts";

export type StatusCounts = Readonly<Record<string, number>>;
type Summary = Readonly<{
  generatedAt: string;
  quoteRequests: StatusCounts;
  openQuotations: number;
  orders: StatusCounts;
}>;
export type BuyerDashboard = Summary &
  Readonly<{
    payments: { onlineEnabled: boolean; testMode: boolean };
  }>;
export type OwnerDashboard = Summary &
  Readonly<{
    printJobs: StatusCounts;
    payments: StatusCounts;
    fulfillments: StatusCounts;
    notifications: { enabled: boolean; counts: StatusCounts };
    setup: {
      ownerMfaEnabled: boolean;
      pricingPolicyActive: boolean;
      onlinePaymentsEnabled: boolean;
      paymentsTestMode: boolean;
    };
  }>;

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function nonnegative(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
function counts(value: unknown): value is StatusCounts {
  return record(value) && Object.values(value).every(nonnegative);
}
function summary(value: unknown): value is Summary & Record<string, unknown> {
  return (
    record(value) &&
    typeof value.generatedAt === "string" &&
    Number.isFinite(Date.parse(value.generatedAt)) &&
    counts(value.quoteRequests) &&
    nonnegative(value.openQuotations) &&
    counts(value.orders)
  );
}
function invalid(): never {
  throw new WorkflowApiError(
    "The dashboard service returned an invalid summary.",
    502,
  );
}

export function parseBuyerDashboard(value: unknown): BuyerDashboard {
  if (
    !summary(value) ||
    !record(value.payments) ||
    typeof value.payments.onlineEnabled !== "boolean" ||
    typeof value.payments.testMode !== "boolean" ||
    (value.payments.testMode && !value.payments.onlineEnabled)
  )
    invalid();
  return value as BuyerDashboard;
}
export function parseOwnerDashboard(value: unknown): OwnerDashboard {
  if (
    !summary(value) ||
    !counts(value.printJobs) ||
    !counts(value.payments) ||
    !counts(value.fulfillments) ||
    !record(value.notifications) ||
    typeof value.notifications.enabled !== "boolean" ||
    !counts(value.notifications.counts) ||
    !record(value.setup) ||
    typeof value.setup.ownerMfaEnabled !== "boolean" ||
    typeof value.setup.pricingPolicyActive !== "boolean" ||
    typeof value.setup.onlinePaymentsEnabled !== "boolean" ||
    typeof value.setup.paymentsTestMode !== "boolean" ||
    (value.setup.paymentsTestMode && !value.setup.onlinePaymentsEnabled)
  )
    invalid();
  return value as OwnerDashboard;
}
export async function getBuyerDashboard(): Promise<BuyerDashboard> {
  return parseBuyerDashboard(await request("/buyer/dashboard"));
}
export async function getOwnerDashboard(): Promise<OwnerDashboard> {
  return parseOwnerDashboard(await request("/owner/dashboard"));
}
export function roleHome(role: "buyer" | "owner"): string {
  return role === "owner" ? "/operations" : "/orders";
}

export function resolveDashboardAccess(
  expected: "buyer" | "owner",
  outcome: unknown,
): { kind: "allow" } | { kind: "redirect"; href: string } | { kind: "unavailable" } {
  if (outcome === "buyer" || outcome === "owner") {
    return outcome === expected
      ? { kind: "allow" }
      : { kind: "redirect", href: roleHome(outcome) };
  }
  if (outcome instanceof AuthApiError && outcome.status === 401) {
    return { kind: "redirect", href: "/sign-in" };
  }
  return { kind: "unavailable" };
}
export function countStates(counts: StatusCounts, ...states: string[]): number {
  return states.reduce((sum, state) => sum + (counts[state] ?? 0), 0);
}
export function totalStates(counts: StatusCounts): number {
  return Object.values(counts).reduce((sum, value) => sum + value, 0);
}
export function ownerAttention(data: OwnerDashboard) {
  return {
    readyToQuote: countStates(
      data.quoteRequests,
      "estimate_ready",
      "owner_review",
    ),
    analysisFailed: countStates(data.quoteRequests, "analysis_failed"),
    paymentReview: countStates(data.orders, "payment_review"),
    activeProduction: countStates(
      data.printJobs,
      "queued",
      "preparing",
      "ready_to_print",
      "authorized",
      "claimed",
      "printing",
      "qa",
    ),
    flaggedJobs: countStates(data.printJobs, "on_hold", "failed"),
    handover: countStates(
      data.orders,
      "ready_for_pickup",
      "out_for_delivery",
      "shipped",
    ),
    notificationFailures: countStates(
      data.notifications.counts,
      "failed",
      "dead_lettered",
    ),
  };
}
export function buyerNextSteps(data: BuyerDashboard) {
  return {
    drafts: countStates(data.quoteRequests, "draft"),
    awaitingOwner: countStates(
      data.quoteRequests,
      "analyzing",
      "analysis_ready",
      "estimate_ready",
      "owner_review",
    ),
    analysisFailed: countStates(data.quoteRequests, "analysis_failed"),
    quotations: data.openQuotations,
    paymentDue: countStates(data.orders, "payment_pending", "payment_failed"),
    paymentProcessing: countStates(data.orders, "payment_processing"),
    production: countStates(
      data.orders,
      "paid_confirmed",
      "queued",
      "preparing",
      "ready_to_print",
      "printing",
      "qa",
    ),
    needsAttention: countStates(
      data.orders,
      "on_hold",
      "print_failed",
      "payment_review",
    ),
    handover: countStates(
      data.orders,
      "ready_for_pickup",
      "out_for_delivery",
      "shipped",
    ),
    completed: countStates(data.orders, "completed"),
  };
}
