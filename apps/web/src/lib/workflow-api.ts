import { readCsrfCookie } from "./auth-api.ts";
import {
  parsePrintSpecification,
  type PrintSpecification,
} from "./print-specification.ts";

export type NotificationSummary = Readonly<{
  id: string;
  templateCode: string;
  status: "pending" | "sent" | "failed" | "dead_lettered";
  attemptCount: number;
  lastErrorCode: string | null;
  createdAt: string;
  availableAt: string;
  sentAt: string | null;
}>;

export async function listNotifications(): Promise<{
  enabled: boolean;
  items: readonly NotificationSummary[];
}> {
  const value = await request("/owner/notifications");
  if (
    !record(value) ||
    typeof value.enabled !== "boolean" ||
    !Array.isArray(value.items)
  )
    throw new Error("Notification service returned an invalid record.");
  const rows: NotificationSummary[] = [];
  for (const row of value.items) {
    if (
      !record(row) ||
      !uuid(row.id) ||
      typeof row.templateCode !== "string" ||
      !["pending", "sent", "failed", "dead_lettered"].includes(
        String(row.status),
      ) ||
      !integer(row.attemptCount) ||
      row.attemptCount < 0 ||
      !nullableText(row.lastErrorCode) ||
      !timestamp(row.createdAt) ||
      !timestamp(row.availableAt) ||
      !nullableTimestamp(row.sentAt)
    )
      throw new Error("Notification service returned an invalid record.");
    rows.push(row as NotificationSummary);
  }
  return { enabled: value.enabled, items: rows };
}

export async function retryNotification(id: string): Promise<void> {
  if (!uuid(id)) throw new Error("Invalid notification ID.");
  await request(`/owner/notifications/${id}/retry`, {});
}

export type Quotation = Readonly<{
  printSpecification?: PrintSpecification | null;
  id: string;
  quoteRequestId: string;
  quoteEstimateId: string;
  version: number;
  status: string;
  currency: "INR";
  subtotalPaise: number;
  adjustmentPaise: number;
  taxPaise: number;
  fulfillmentPaise: number;
  totalPaise: number;
  ownerReason: string | null;
  issuedAt: string;
  expiresAt: string;
  acceptedAt: string | null;
  fulfillmentMode?: "pickup" | "local_delivery" | "shipping";
  quantity?: number;
}>;

export type Order = Readonly<{
  printSpecification?: PrintSpecification | null;
  id: string;
  publicReference: string;
  acceptedQuoteId: string;
  status: string;
  version: number;
  currency: "INR";
  amountPaise: number;
  acceptedAt: string;
  completedAt: string | null;
}>;

export type PrintJob = Readonly<{
  id: string;
  orderId: string;
  status: string;
  version: number;
  sequence: number;
  queueRank: number | null;
  attemptNumber: number;
  ownerNote: string | null;
  queuedAt: string;
  startedAt: string | null;
  completedAt: string | null;
}>;

export type Fulfillment = Readonly<{
  mode: "pickup" | "local_delivery" | "shipping";
  status: string;
  destination: Address | null;
  chargePaise: number;
  carrierName: string | null;
  trackingReference: string | null;
  dispatchedAt: string | null;
  completedAt: string | null;
}>;

export type OrderDetail = Order &
  Readonly<{
    lines: readonly {
      kind: string;
      description: string;
      amountPaise: number;
    }[];
    fulfillment: Fulfillment | null;
    timeline: readonly {
      event: string;
      at: string;
      progressBps: number | null;
    }[];
    payment: { checkoutEnabled: boolean; testMode: boolean; message: string };
  }>;

export type Address = Readonly<{
  recipientName: string;
  phoneE164: string;
  line1: string;
  line2: string;
  locality: string;
  district: string;
  state: string;
  postalCode: string;
  countryCode: "IN";
}>;

export class WorkflowApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function integer(value: unknown): value is number {
  return Number.isSafeInteger(value);
}
function uuid(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value)
  );
}
function timestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}
function nullableText(value: unknown): boolean {
  return value === null || typeof value === "string";
}
function nullableTimestamp(value: unknown): boolean {
  return value === null || timestamp(value);
}
function destination(value: unknown): value is Address | null {
  if (value === null) return true;
  if (!record(value) || value.countryCode !== "IN") return false;
  return (
    [
      "recipientName",
      "phoneE164",
      "line1",
      "line2",
      "locality",
      "district",
      "state",
      "postalCode",
    ].every((field) => typeof value[field] === "string") &&
    /^\+91[6-9][0-9]{9}$/.test(String(value.phoneE164)) &&
    /^[1-9][0-9]{5}$/.test(String(value.postalCode))
  );
}

async function request(path: string, body?: unknown): Promise<unknown> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) {
    const csrf = readCsrfCookie(document.cookie);
    if (!csrf)
      throw new WorkflowApiError("Sign in again before making changes.", 401);
    headers["X-CSRF-Token"] = csrf;
    headers["Content-Type"] = "application/json";
  }
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method: body === undefined ? "GET" : "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new WorkflowApiError("The service is unavailable. Try again.", 0);
  }
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new WorkflowApiError(
      record(value) && typeof value.detail === "string"
        ? value.detail
        : "This request could not be completed. Check the details and try again.",
      response.status,
    );
  }
  return value;
}

function invalid(): never {
  throw new WorkflowApiError("The service returned an invalid record.", 502);
}

function quotation(value: unknown): Quotation {
  if (
    !record(value) ||
    !uuid(value.id) ||
    !uuid(value.quoteRequestId) ||
    !uuid(value.quoteEstimateId) ||
    !integer(value.version) ||
    value.version < 1 ||
    typeof value.status !== "string" ||
    value.currency !== "INR" ||
    ![
      value.subtotalPaise,
      value.adjustmentPaise,
      value.taxPaise,
      value.fulfillmentPaise,
      value.totalPaise,
    ].every(integer) ||
    !timestamp(value.expiresAt) ||
    !timestamp(value.issuedAt) ||
    !nullableTimestamp(value.acceptedAt) ||
    !nullableText(value.ownerReason) ||
    (value.fulfillmentMode !== undefined &&
      !["pickup", "local_delivery", "shipping"].includes(
        String(value.fulfillmentMode),
      )) ||
    (value.quantity !== undefined &&
      (!integer(value.quantity) || value.quantity < 1))
  )
    return invalid();
  return {
    ...value,
    printSpecification: parsePrintSpecification(value.printSpecification),
  } as unknown as Quotation;
}
function order(value: unknown): Order {
  if (
    !record(value) ||
    !uuid(value.id) ||
    !uuid(value.acceptedQuoteId) ||
    !integer(value.version) ||
    typeof value.publicReference !== "string" ||
    typeof value.status !== "string" ||
    value.currency !== "INR" ||
    !integer(value.amountPaise) ||
    value.amountPaise <= 0 ||
    value.version < 1 ||
    !timestamp(value.acceptedAt) ||
    !nullableTimestamp(value.completedAt)
  )
    return invalid();
  return {
    ...value,
    printSpecification: parsePrintSpecification(value.printSpecification),
  } as unknown as Order;
}
function job(value: unknown): PrintJob {
  if (
    !record(value) ||
    !uuid(value.id) ||
    !uuid(value.orderId) ||
    !integer(value.version) ||
    typeof value.status !== "string" ||
    !integer(value.sequence) ||
    value.sequence < 1 ||
    value.version < 1 ||
    !integer(value.attemptNumber) ||
    value.attemptNumber < 1 ||
    !nullableText(value.ownerNote) ||
    !(value.queueRank === null || integer(value.queueRank)) ||
    !timestamp(value.queuedAt) ||
    !nullableTimestamp(value.startedAt) ||
    !nullableTimestamp(value.completedAt)
  )
    return invalid();
  return value as unknown as PrintJob;
}
function items<T>(value: unknown, parse: (row: unknown) => T): readonly T[] {
  if (!record(value) || !Array.isArray(value.items)) return invalid();
  return value.items.map(parse);
}

export const listQuotations = async () =>
  items(await request("/quotations"), quotation);
export const listOrders = async () => items(await request("/orders"), order);
export const listProduction = async () =>
  items(await request("/owner/production"), job);

export type Checkout = Readonly<{
  intentId: string;
  keyId: string;
  displayName: string;
  providerOrderId: string;
  amountPaise: number;
  currency: "INR";
  testMode: boolean;
}>;

export async function createCheckout(orderId: string): Promise<Checkout> {
  const value = await request(`/orders/${orderId}/checkout`, {});
  if (
    !record(value) ||
    !uuid(value.intentId) ||
    typeof value.displayName !== "string" ||
    !value.displayName.trim() ||
    value.displayName.length > 120 ||
    typeof value.keyId !== "string" ||
    !/^rzp_(test|live)_[A-Za-z0-9]+$/.test(value.keyId) ||
    typeof value.providerOrderId !== "string" ||
    !/^order_[A-Za-z0-9]+$/.test(value.providerOrderId) ||
    !integer(value.amountPaise) ||
    value.amountPaise <= 0 ||
    value.currency !== "INR" ||
    typeof value.testMode !== "boolean" ||
    value.keyId.startsWith("rzp_test_") !== value.testMode
  )
    invalid();
  return value as Checkout;
}

export async function returnCheckout(
  orderId: string,
  response: {
    razorpay_payment_id: string;
    razorpay_order_id: string;
    razorpay_signature: string;
  },
): Promise<Order> {
  return order(
    await request(`/orders/${orderId}/checkout-return`, {
      paymentId: response.razorpay_payment_id,
      providerOrderId: response.razorpay_order_id,
      signature: response.razorpay_signature,
    }),
  );
}

export async function reconcilePayment(
  orderId: string,
  owner = false,
): Promise<Order> {
  return order(
    await request(`${owner ? "/owner" : ""}/orders/${orderId}/reconcile`, {}),
  );
}

export type PaymentSummary = Readonly<{
  id: string;
  orderId: string;
  publicReference: string;
  status: string;
  orderStatus: string;
  amountPaise: number;
  currency: "INR";
  testMode: boolean;
  failureCode: string | null;
  providerOrderId: string | null;
  lastReconciledAt: string | null;
}>;

export async function listPayments(): Promise<readonly PaymentSummary[]> {
  return items(await request("/owner/payments"), (value) => {
    if (
      !record(value) ||
      !uuid(value.id) ||
      !uuid(value.orderId) ||
      typeof value.publicReference !== "string" ||
      typeof value.status !== "string" ||
      typeof value.orderStatus !== "string" ||
      !integer(value.amountPaise) ||
      value.amountPaise <= 0 ||
      value.currency !== "INR" ||
      typeof value.testMode !== "boolean" ||
      !nullableText(value.failureCode) ||
      !nullableText(value.providerOrderId) ||
      !nullableTimestamp(value.lastReconciledAt)
    )
      invalid();
    return value as PaymentSummary;
  });
}

export async function getOrder(id: string): Promise<OrderDetail> {
  const value = await request(`/orders/${id}`);
  order(value);
  if (
    !record(value) ||
    !Array.isArray(value.lines) ||
    !Array.isArray(value.timeline) ||
    !record(value.payment) ||
    typeof value.payment.checkoutEnabled !== "boolean" ||
    typeof value.payment.testMode !== "boolean" ||
    typeof value.payment.message !== "string" ||
    value.lines.some(
      (line) =>
        !record(line) ||
        typeof line.kind !== "string" ||
        typeof line.description !== "string" ||
        !integer(line.amountPaise),
    ) ||
    value.timeline.some(
      (event) =>
        !record(event) ||
        typeof event.event !== "string" ||
        !timestamp(event.at) ||
        !(event.progressBps === null || integer(event.progressBps)),
    ) ||
    !(
      value.fulfillment === null ||
      (record(value.fulfillment) &&
        ["pickup", "local_delivery", "shipping"].includes(
          String(value.fulfillment.mode),
        ) &&
        typeof value.fulfillment.status === "string" &&
        destination(value.fulfillment.destination) &&
        integer(value.fulfillment.chargePaise) &&
        nullableText(value.fulfillment.carrierName) &&
        nullableText(value.fulfillment.trackingReference) &&
        nullableTimestamp(value.fulfillment.dispatchedAt) &&
        nullableTimestamp(value.fulfillment.completedAt))
    )
  )
    return invalid();
  return value as unknown as OrderDetail;
}

export async function issueQuotation(
  requestId: string,
  input: {
    estimateId: string;
    expectedVersion: number;
    expiresAt: string;
    adjustmentPaise: number;
    fulfillmentPaise: number;
    reason: string | null;
  },
): Promise<Quotation> {
  return quotation(
    await request(`/owner/quote-requests/${requestId}/quotations`, input),
  );
}

export const rejectQuoteRequest = (
  id: string,
  expectedVersion: number,
  reason: string,
) => request(`/owner/quote-requests/${id}/reject`, { expectedVersion, reason });
export const retrySlicing = (id: string, expectedVersion: number) =>
  request(`/owner/quote-requests/${id}/analysis-retry`, { expectedVersion });
export const acceptQuotation = async (id: string, address?: Address) =>
  order(
    await request(`/quotations/${id}/accept`, { address: address ?? null }),
  );
export const changeJob = async (
  id: string,
  expectedVersion: number,
  action: string,
  note?: string,
) =>
  job(
    await request(`/owner/production/${id}/actions`, {
      expectedVersion,
      action,
      note: note || null,
    }),
  );
export const saveReadiness = async (
  id: string,
  expectedVersion: number,
  checks: Record<string, boolean>,
) =>
  job(
    await request(`/owner/production/${id}/readiness`, {
      expectedVersion,
      ...checks,
    }),
  );
export const changeFulfillment = (
  id: string,
  expectedVersion: number,
  status: string,
  carrierName?: string,
  trackingReference?: string,
) =>
  request(`/owner/orders/${id}/fulfillment`, {
    expectedVersion,
    status,
    carrierName: carrierName || null,
    trackingReference: trackingReference || null,
  });
export const requestBridgePairing = (name: string) =>
  request("/owner/bridges/pairing", { name });
export const revokeBridge = (id: string) =>
  request(`/owner/bridges/${id}/revoke`, {});
export const authorizeHandoff = (id: string, expectedVersion: number) =>
  request(`/owner/production/${id}/handoff`, { expectedVersion });
export async function listBridges(): Promise<
  readonly {
    id: string;
    name: string;
    status: string;
    lastHeartbeatAt: string | null;
  }[]
> {
  const value = await request("/owner/bridges");
  if (
    !record(value) ||
    !Array.isArray(value.items) ||
    value.items.some(
      (row) =>
        !record(row) ||
        !uuid(row.id) ||
        typeof row.name !== "string" ||
        typeof row.status !== "string" ||
        !nullableTimestamp(row.lastHeartbeatAt),
    )
  )
    return invalid();
  return value.items;
}
export async function createBridgePairing(
  name: string,
): Promise<{ pairingToken: string; expiresAt: string }> {
  const value = await requestBridgePairing(name);
  if (
    !record(value) ||
    typeof value.pairingToken !== "string" ||
    !timestamp(value.expiresAt)
  )
    return invalid();
  return { pairingToken: value.pairingToken, expiresAt: value.expiresAt };
}

export async function getArtifacts(id: string): Promise<
  readonly {
    id: string;
    sha256: string;
    position: number;
    quantity: number;
    downloadUrl: string;
  }[]
> {
  const value = await request(`/owner/production/${id}/artifacts`);
  if (
    !record(value) ||
    !Array.isArray(value.items) ||
    value.items.some(
      (item) =>
        !record(item) ||
        !uuid(item.id) ||
        typeof item.sha256 !== "string" ||
        !/^[0-9a-f]{64}$/.test(item.sha256) ||
        !integer(item.position) ||
        item.position < 1 ||
        !integer(item.quantity) ||
        item.quantity < 1 ||
        item.downloadUrl !==
          `/api/v1/owner/production/${id}/artifacts/${item.id}`,
    )
  )
    return invalid();
  return value.items;
}

export function parseRupees(value: string, signed = false): number {
  const match = (
    signed ? /^(-?)(\d+)(?:\.(\d{1,2}))?$/ : /^()(\d+)(?:\.(\d{1,2}))?$/
  ).exec(value.trim());
  if (!match)
    throw new Error("Enter a rupee amount with at most two decimal places.");
  const paise =
    Number(match[2]) * 100 + Number((match[3] ?? "").padEnd(2, "0"));
  if (!Number.isSafeInteger(paise) || paise > 100_000_000)
    throw new Error("This amount is too large.");
  return match[1] === "-" ? -paise : paise;
}

export function formatMoney(paise: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
  }).format(paise / 100);
}
