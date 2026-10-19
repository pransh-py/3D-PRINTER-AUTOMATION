import { readCsrfCookie } from "./auth-api.ts";

const OWNER_API_BASE = "/api/v1/owner";

export type MaterialRate = Readonly<{
  id: string;
  code: string;
  displayName: string;
  ratePaisePerGram: number;
}>;

export type PricingPolicy = Readonly<{
  id: string;
  version: number;
  status: "draft" | "active" | "retired";
  currency: "INR";
  machineRatePaisePerHour: number;
  setupFeePaise: number;
  minimumOrderPaise: number;
  contingencyBps: number;
  taxBps: number;
  estimateValidityHours: number;
  materials: readonly MaterialRate[];
  activatedAt: string | null;
  createdAt: string;
}>;

export type CreatePricingPolicyInput = Readonly<{
  machineRatePaisePerHour: number;
  setupFeePaise: number;
  minimumOrderPaise: number;
  contingencyBps: number;
  taxBps: number;
  estimateValidityHours: number;
  materials: readonly Readonly<{
    code: string;
    displayName: string;
    ratePaisePerGram: number;
  }>[];
}>;

export class PricingApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "PricingApiError";
    this.status = status;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function parseMaterial(payload: unknown): MaterialRate {
  if (
    !isRecord(payload) ||
    typeof payload.id !== "string" ||
    typeof payload.code !== "string" ||
    typeof payload.displayName !== "string" ||
    !isNonNegativeInteger(payload.ratePaisePerGram)
  ) {
    throw new PricingApiError("The pricing service returned an invalid material.", 502);
  }
  return {
    id: payload.id,
    code: payload.code,
    displayName: payload.displayName,
    ratePaisePerGram: payload.ratePaisePerGram,
  };
}

function parsePolicy(payload: unknown): PricingPolicy {
  if (
    !isRecord(payload) ||
    typeof payload.id !== "string" ||
    !isNonNegativeInteger(payload.version) || payload.version < 1 ||
    !["draft", "active", "retired"].includes(String(payload.status)) ||
    payload.currency !== "INR" ||
    !isNonNegativeInteger(payload.machineRatePaisePerHour) ||
    !isNonNegativeInteger(payload.setupFeePaise) ||
    !isNonNegativeInteger(payload.minimumOrderPaise) ||
    !isNonNegativeInteger(payload.contingencyBps) ||
    !isNonNegativeInteger(payload.taxBps) ||
    !isNonNegativeInteger(payload.estimateValidityHours) || payload.estimateValidityHours < 1 ||
    !Array.isArray(payload.materials) ||
    (payload.activatedAt !== null && typeof payload.activatedAt !== "string") ||
    typeof payload.createdAt !== "string"
  ) {
    throw new PricingApiError("The pricing service returned an invalid policy.", 502);
  }
  return {
    id: payload.id,
    version: payload.version,
    status: payload.status as PricingPolicy["status"],
    currency: "INR",
    machineRatePaisePerHour: payload.machineRatePaisePerHour,
    setupFeePaise: payload.setupFeePaise,
    minimumOrderPaise: payload.minimumOrderPaise,
    contingencyBps: payload.contingencyBps,
    taxBps: payload.taxBps,
    estimateValidityHours: payload.estimateValidityHours,
    materials: payload.materials.map(parseMaterial),
    activatedAt: payload.activatedAt as string | null,
    createdAt: payload.createdAt,
  };
}

function csrf(cookieString: string): string {
  const value = readCsrfCookie(cookieString);
  if (value === null) {
    throw new PricingApiError("Your session has expired. Please sign in again.", 401);
  }
  return value;
}

async function request(path: string, init: RequestInit = {}): Promise<unknown> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(`${OWNER_API_BASE}${path}`, {
      ...init,
      headers,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new PricingApiError("The pricing service is unavailable.", 0);
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // A non-JSON error is translated below without exposing its body.
  }
  if (!response.ok) {
    const detail = isRecord(payload) && typeof payload.detail === "string"
      ? payload.detail
      : "The pricing operation could not be completed.";
    throw new PricingApiError(detail, response.status);
  }
  return payload;
}

export async function listPricingPolicies(): Promise<readonly PricingPolicy[]> {
  const payload = await request("/pricing-policies");
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    throw new PricingApiError("The pricing service returned an invalid list.", 502);
  }
  return payload.items.map(parsePolicy);
}

export async function createPricingPolicy(
  input: CreatePricingPolicyInput,
  cookieString: string,
): Promise<PricingPolicy> {
  return parsePolicy(await request("/pricing-policies", {
    method: "POST",
    headers: { "X-CSRF-Token": csrf(cookieString) },
    body: JSON.stringify(input),
  }));
}

export async function activatePricingPolicy(
  policyId: string,
  cookieString: string,
): Promise<PricingPolicy> {
  return parsePolicy(await request(`/pricing-policies/${policyId}/activate`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrf(cookieString) },
  }));
}

export async function createQuoteEstimate(
  quoteId: string,
  input: Readonly<{
    clientToken: string;
    expectedQuoteVersion: number;
    analysisRunId: string;
    materialCode: string;
  }>,
  cookieString: string,
): Promise<void> {
  const payload = await request(`/quote-requests/${quoteId}/estimates`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrf(cookieString) },
    body: JSON.stringify(input),
  });
  if (!isRecord(payload) || typeof payload.id !== "string" || !isNonNegativeInteger(payload.totalPaise)) {
    throw new PricingApiError("The pricing service returned an invalid estimate.", 502);
  }
}
