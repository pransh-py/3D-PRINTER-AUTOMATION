import { readCsrfCookie } from "./auth-api.ts";

const QUOTE_API_BASE = "/api/v1/quote-requests";

export const SUPPORTED_MODEL_EXTENSIONS = [".stl", ".3mf", ".obj", ".step", ".stp"] as const;
export const MAX_MODEL_FILE_BYTES = 100 * 1024 * 1024;
export const MAX_MODEL_FILES_PER_QUOTE = 5;

export type QuoteRequestStatus =
  | "draft"
  | "analyzing"
  | "analysis_failed"
  | "estimate_ready"
  | "owner_review"
  | "quoted"
  | "rejected";

export type ModelAssetStatus =
  | "pending_upload"
  | "quarantined"
  | "validating"
  | "validated"
  | "rejected";

export type ModelFormat = "stl" | "3mf" | "obj" | "step";

export type ModelAsset = Readonly<{
  id: string;
  filename: string;
  format: ModelFormat;
  status: ModelAssetStatus;
  expectedSizeBytes: number;
  actualSizeBytes: number | null;
  claimedSha256: string;
  verifiedSha256: string | null;
  uploadExpiresAt: string;
  uploadedAt: string | null;
  rejectionCode: string | null;
  createdAt: string;
}>;

export type QuoteRequest = Readonly<{
  id: string;
  buyerId: string;
  status: QuoteRequestStatus;
  version: number;
  submittedAt: string | null;
  createdAt: string;
  updatedAt: string;
  assets: readonly ModelAsset[];
}>;

export type QuoteRequestList = Readonly<{
  items: readonly QuoteRequest[];
  total: number;
  limit: number;
  offset: number;
}>;

export type PresignedUpload = Readonly<{
  url: string;
  fields: Readonly<Record<string, string>>;
  expiresAt: string;
}>;

export type ModelUploadIntent = Readonly<{
  asset: ModelAsset;
  upload: PresignedUpload;
}>;

export type ModelFileRejectionReason = "unsupported_format" | "empty_file" | "file_too_large";

export type ModelFileRejection = Readonly<{
  file: File;
  reason: ModelFileRejectionReason;
}>;

export type ModelSelectionValidation = Readonly<{
  accepted: readonly File[];
  rejected: readonly ModelFileRejection[];
  tooMany: boolean;
}>;

export class QuoteApiError extends Error {
  readonly status: number;
  readonly retryAfterSeconds: number | null;

  constructor(message: string, status: number, retryAfterSeconds: number | null = null) {
    super(message);
    this.name = "QuoteApiError";
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function responseMessage(payload: unknown, fallback: string): string {
  if (isRecord(payload) && typeof payload.detail === "string") {
    return payload.detail;
  }
  if (isRecord(payload) && Array.isArray(payload.detail)) {
    return "Please check the highlighted information and try again.";
  }
  return fallback;
}

async function readPayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return null;
  }
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function parseRetryAfter(response: Response): number | null {
  const value = response.headers.get("retry-after");
  if (value === null || !/^\d+$/.test(value)) {
    return null;
  }
  return Number(value);
}

function requiredCsrfToken(cookieString: string): string {
  const token = readCsrfCookie(cookieString);
  if (token === null) {
    throw new QuoteApiError("Your session has expired. Please sign in again.", 401);
  }
  return token;
}

async function request(
  path: string,
  init: Readonly<{
    method?: "GET" | "POST";
    body?: unknown;
    csrfToken?: string;
  }> = {},
): Promise<unknown> {
  const headers = new Headers({ Accept: "application/json" });
  let body: string | undefined;
  if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.body);
  }
  if (init.csrfToken !== undefined) {
    headers.set("X-CSRF-Token", init.csrfToken);
  }

  let response: Response;
  try {
    response = await fetch(`${QUOTE_API_BASE}${path}`, {
      method: init.method ?? "GET",
      headers,
      body,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new QuoteApiError("The quote service is unavailable. Please try again.", 0);
  }

  if (!response.ok) {
    const payload = await readPayload(response);
    throw new QuoteApiError(
      responseMessage(payload, "The quote request could not be completed."),
      response.status,
      parseRetryAfter(response),
    );
  }

  if (response.status === 204) {
    return null;
  }
  const payload = await readPayload(response);
  if (payload === null) {
    throw new QuoteApiError("The quote service returned an invalid response.", 502);
  }
  return payload;
}

const QUOTE_REQUEST_STATUSES = new Set<string>([
  "draft",
  "analyzing",
  "analysis_failed",
  "estimate_ready",
  "owner_review",
  "quoted",
  "rejected",
]);

const MODEL_ASSET_STATUSES = new Set<string>([
  "pending_upload",
  "quarantined",
  "validating",
  "validated",
  "rejected",
]);

const MODEL_FORMATS = new Set<string>(["stl", "3mf", "obj", "step"]);

function parseModelAsset(payload: unknown): ModelAsset {
  if (
    !isRecord(payload) ||
    typeof payload.id !== "string" ||
    typeof payload.filename !== "string" ||
    typeof payload.format !== "string" ||
    !MODEL_FORMATS.has(payload.format) ||
    typeof payload.status !== "string" ||
    !MODEL_ASSET_STATUSES.has(payload.status) ||
    typeof payload.expectedSizeBytes !== "number" ||
    (payload.actualSizeBytes !== null && typeof payload.actualSizeBytes !== "number") ||
    typeof payload.claimedSha256 !== "string" ||
    (payload.verifiedSha256 !== null && typeof payload.verifiedSha256 !== "string") ||
    typeof payload.uploadExpiresAt !== "string" ||
    (payload.uploadedAt !== null && typeof payload.uploadedAt !== "string") ||
    (payload.rejectionCode !== null && typeof payload.rejectionCode !== "string") ||
    typeof payload.createdAt !== "string"
  ) {
    throw new QuoteApiError("The quote service returned an invalid model response.", 502);
  }
  return {
    id: payload.id,
    filename: payload.filename,
    format: payload.format as ModelFormat,
    status: payload.status as ModelAssetStatus,
    expectedSizeBytes: payload.expectedSizeBytes,
    actualSizeBytes: payload.actualSizeBytes as number | null,
    claimedSha256: payload.claimedSha256,
    verifiedSha256: payload.verifiedSha256 as string | null,
    uploadExpiresAt: payload.uploadExpiresAt,
    uploadedAt: payload.uploadedAt as string | null,
    rejectionCode: payload.rejectionCode as string | null,
    createdAt: payload.createdAt,
  };
}

function parseQuoteRequest(payload: unknown): QuoteRequest {
  if (
    !isRecord(payload) ||
    typeof payload.id !== "string" ||
    typeof payload.buyerId !== "string" ||
    typeof payload.status !== "string" ||
    !QUOTE_REQUEST_STATUSES.has(payload.status) ||
    typeof payload.version !== "number" ||
    (payload.submittedAt !== null && typeof payload.submittedAt !== "string") ||
    typeof payload.createdAt !== "string" ||
    typeof payload.updatedAt !== "string" ||
    !Array.isArray(payload.assets)
  ) {
    throw new QuoteApiError("The quote service returned an invalid response.", 502);
  }
  return {
    id: payload.id,
    buyerId: payload.buyerId,
    status: payload.status as QuoteRequestStatus,
    version: payload.version,
    submittedAt: payload.submittedAt as string | null,
    createdAt: payload.createdAt,
    updatedAt: payload.updatedAt,
    assets: payload.assets.map(parseModelAsset),
  };
}

function parseQuoteRequestList(payload: unknown): QuoteRequestList {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.items) ||
    typeof payload.total !== "number" ||
    typeof payload.limit !== "number" ||
    typeof payload.offset !== "number"
  ) {
    throw new QuoteApiError("The quote service returned an invalid list response.", 502);
  }
  return {
    items: payload.items.map(parseQuoteRequest),
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
  };
}

function parseModelUploadIntent(payload: unknown): ModelUploadIntent {
  if (!isRecord(payload) || !isRecord(payload.upload)) {
    throw new QuoteApiError("The quote service returned an invalid upload response.", 502);
  }
  const upload = payload.upload;
  if (
    typeof upload.url !== "string" ||
    !isRecord(upload.fields) ||
    !Object.values(upload.fields).every((value) => typeof value === "string") ||
    typeof upload.expiresAt !== "string"
  ) {
    throw new QuoteApiError("The quote service returned an invalid upload response.", 502);
  }
  return {
    asset: parseModelAsset(payload.asset),
    upload: {
      url: upload.url,
      fields: upload.fields as Record<string, string>,
      expiresAt: upload.expiresAt,
    },
  };
}

function fileExtension(filename: string): string {
  const index = filename.lastIndexOf(".");
  return index === -1 ? "" : filename.slice(index).toLowerCase();
}

/** Rejects unsupported, zero-byte, oversized, or too-numerous files before any network work. */
export function validateModelSelection(files: readonly File[]): ModelSelectionValidation {
  const rejected: ModelFileRejection[] = [];
  const accepted: File[] = [];
  for (const file of files) {
    const extension = fileExtension(file.name);
    if (!(SUPPORTED_MODEL_EXTENSIONS as readonly string[]).includes(extension)) {
      rejected.push({ file, reason: "unsupported_format" });
      continue;
    }
    if (file.size <= 0) {
      rejected.push({ file, reason: "empty_file" });
      continue;
    }
    if (file.size > MAX_MODEL_FILE_BYTES) {
      rejected.push({ file, reason: "file_too_large" });
      continue;
    }
    accepted.push(file);
  }
  return {
    accepted,
    rejected,
    tooMany: files.length > MAX_MODEL_FILES_PER_QUOTE,
  };
}

/** Computes a lowercase hex SHA-256 digest of a file's contents using the browser Web Crypto API. */
export async function computeFileSha256(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export async function createQuoteRequest(
  clientToken: string,
  cookieString: string,
): Promise<QuoteRequest> {
  return parseQuoteRequest(
    await request("", {
      method: "POST",
      body: { clientToken },
      csrfToken: requiredCsrfToken(cookieString),
    }),
  );
}

export async function listQuoteRequests(
  limit = 20,
  offset = 0,
): Promise<QuoteRequestList> {
  return parseQuoteRequestList(await request(`?limit=${limit}&offset=${offset}`));
}

export async function issueModelUpload(
  requestId: string,
  input: Readonly<{
    clientToken: string;
    filename: string;
    sizeBytes: number;
    sha256: string;
  }>,
  cookieString: string,
): Promise<ModelUploadIntent> {
  return parseModelUploadIntent(
    await request(`/${requestId}/uploads`, {
      method: "POST",
      body: input,
      csrfToken: requiredCsrfToken(cookieString),
    }),
  );
}

/**
 * Uploads a file directly to private storage using the signed POST policy.
 * Every returned field is appended first, then the file is appended last as "file".
 * No credentials or custom headers are sent to the storage endpoint.
 */
export async function uploadModelToStorage(upload: PresignedUpload, file: File): Promise<void> {
  const formData = new FormData();
  for (const [name, value] of Object.entries(upload.fields)) {
    formData.append(name, value);
  }
  formData.append("file", file);

  let response: Response;
  try {
    response = await fetch(upload.url, { method: "POST", body: formData });
  } catch {
    throw new QuoteApiError("The upload could not reach private storage. Please try again.", 0);
  }
  if (!response.ok) {
    throw new QuoteApiError(
      "The upload was rejected by private storage. Please try again.",
      response.status,
    );
  }
}

export async function completeModelUpload(
  requestId: string,
  assetId: string,
  cookieString: string,
): Promise<ModelAsset> {
  return parseModelAsset(
    await request(`/${requestId}/uploads/${assetId}/complete`, {
      method: "POST",
      csrfToken: requiredCsrfToken(cookieString),
    }),
  );
}

export async function submitQuoteRequest(
  requestId: string,
  cookieString: string,
): Promise<QuoteRequest> {
  return parseQuoteRequest(
    await request(`/${requestId}/submit`, {
      method: "POST",
      csrfToken: requiredCsrfToken(cookieString),
    }),
  );
}
