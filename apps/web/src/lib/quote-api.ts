import { readCsrfCookie } from "./auth-api.ts";

const QUOTE_API_BASE = "/api/v1/quote-requests";

export const SUPPORTED_MODEL_EXTENSIONS = [".stl", ".3mf", ".obj", ".step", ".stp"] as const;
export const MAX_MODEL_FILE_BYTES = 100 * 1024 * 1024;
export const MAX_MODEL_FILES_PER_QUOTE = 5;

export type QuoteRequestStatus =
  | "draft"
  | "analyzing"
  | "analysis_failed"
  | "analysis_ready"
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

export type AnalysisRunStatus = "queued" | "running" | "awaiting_profile" | "succeeded" | "failed";

export type AnalysisAssetStatus = "validated" | "awaiting_profile" | "sliced" | "rejected";

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

export type AnalysisAssetResult = Readonly<{
  assetId: string;
  status: AnalysisAssetStatus;
  detectedFormat: ModelFormat | null;
  verifiedSha256: string | null;
  dimensionsUm: readonly [number, number, number] | null;
  triangleCount: number | null;
  objectCount: number | null;
  fitsBuildVolume: boolean | null;
  warningCodes: readonly string[];
  filamentMg: number | null;
  durationSeconds: number | null;
  failureCode: string | null;
}>;

export type AnalysisRun = Readonly<{
  id: string;
  requestVersion: number;
  status: AnalysisRunStatus;
  attemptCount: number;
  validatorVersion: string;
  slicerName: string | null;
  slicerVersion: string | null;
  profileSha256: string | null;
  queuedAt: string;
  startedAt: string | null;
  completedAt: string | null;
  failureCode: string | null;
  assets: readonly AnalysisAssetResult[];
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
  latestAnalysis: AnalysisRun | null;
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
  "analysis_ready",
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

const ANALYSIS_RUN_STATUSES = new Set<string>([
  "queued",
  "running",
  "awaiting_profile",
  "succeeded",
  "failed",
]);

const ANALYSIS_ASSET_STATUSES = new Set<string>([
  "validated",
  "awaiting_profile",
  "sliced",
  "rejected",
]);

const HEX_SHA256_PATTERN = /^[0-9a-f]{64}$/;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const ISO_TIMESTAMP_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/;

const UTC_OFFSET_PATTERN = /^[+-](\d{2}):(\d{2})$/;

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1;
}

function isNullableHex64(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && HEX_SHA256_PATTERN.test(value));
}

function isDimensionsTriple(value: unknown): value is readonly [number, number, number] {
  return Array.isArray(value) && value.length === 3 && value.every(isNonNegativeInteger);
}

/** Strict RFC 4122 UUID shape check, used for the analysis run and asset-result identifiers. */
function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

/**
 * Validates a "Z" or numeric UTC-offset suffix. Offset hours must be 00-14 and minutes 00-59,
 * with hour 14 permitting only minute 00 (the widest real-world UTC offset is +14:00).
 */
function isValidUtcOffset(offset: string): boolean {
  if (offset === "Z") {
    return true;
  }
  const match = UTC_OFFSET_PATTERN.exec(offset);
  if (match === null) {
    return false;
  }
  const [, hourText, minuteText] = match;
  const hours = Number(hourText);
  const minutes = Number(minuteText);
  if (hours > 14 || minutes > 59) {
    return false;
  }
  if (hours === 14 && minutes !== 0) {
    return false;
  }
  return true;
}

/**
 * Strict ISO-8601 timestamp check accepting the backend's "Z" or numeric UTC-offset forms and
 * rejecting impossible calendar, clock, or offset values (e.g. month 13, February 30, hour 24,
 * offset +99:99).
 */
function isIsoTimestamp(value: unknown): value is string {
  if (typeof value !== "string") {
    return false;
  }
  const match = ISO_TIMESTAMP_PATTERN.exec(value);
  if (match === null) {
    return false;
  }
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, offsetText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  if (month < 1 || month > 12) {
    return false;
  }
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  if (day < 1 || day > daysInMonth || hour > 23 || minute > 59 || second > 59) {
    return false;
  }
  return isValidUtcOffset(offsetText);
}

function isNullableIsoTimestamp(value: unknown): value is string | null {
  return value === null || isIsoTimestamp(value);
}

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

function parseAnalysisAssetResult(payload: unknown): AnalysisAssetResult {
  if (
    !isRecord(payload) ||
    !isUuid(payload.assetId) ||
    typeof payload.status !== "string" ||
    !ANALYSIS_ASSET_STATUSES.has(payload.status) ||
    (payload.detectedFormat !== null &&
      (typeof payload.detectedFormat !== "string" || !MODEL_FORMATS.has(payload.detectedFormat))) ||
    !isNullableHex64(payload.verifiedSha256) ||
    (payload.dimensionsUm !== null && !isDimensionsTriple(payload.dimensionsUm)) ||
    (payload.triangleCount !== null && !isNonNegativeInteger(payload.triangleCount)) ||
    (payload.objectCount !== null && !isNonNegativeInteger(payload.objectCount)) ||
    (payload.fitsBuildVolume !== null && typeof payload.fitsBuildVolume !== "boolean") ||
    !Array.isArray(payload.warningCodes) ||
    !payload.warningCodes.every((code) => typeof code === "string") ||
    (payload.filamentMg !== null && !isNonNegativeInteger(payload.filamentMg)) ||
    (payload.durationSeconds !== null && !isNonNegativeInteger(payload.durationSeconds)) ||
    (payload.failureCode !== null && typeof payload.failureCode !== "string")
  ) {
    throw new QuoteApiError("The quote service returned an invalid analysis result.", 502);
  }
  return {
    assetId: payload.assetId,
    status: payload.status as AnalysisAssetStatus,
    detectedFormat: payload.detectedFormat as ModelFormat | null,
    verifiedSha256: payload.verifiedSha256 as string | null,
    dimensionsUm: payload.dimensionsUm as readonly [number, number, number] | null,
    triangleCount: payload.triangleCount as number | null,
    objectCount: payload.objectCount as number | null,
    fitsBuildVolume: payload.fitsBuildVolume as boolean | null,
    warningCodes: payload.warningCodes as readonly string[],
    filamentMg: payload.filamentMg as number | null,
    durationSeconds: payload.durationSeconds as number | null,
    failureCode: payload.failureCode as string | null,
  };
}

function parseAnalysisRun(payload: unknown): AnalysisRun {
  if (
    !isRecord(payload) ||
    !isUuid(payload.id) ||
    !isPositiveInteger(payload.requestVersion) ||
    typeof payload.status !== "string" ||
    !ANALYSIS_RUN_STATUSES.has(payload.status) ||
    !isNonNegativeInteger(payload.attemptCount) ||
    typeof payload.validatorVersion !== "string" ||
    payload.validatorVersion.length === 0 ||
    (payload.slicerName !== null && typeof payload.slicerName !== "string") ||
    (payload.slicerVersion !== null && typeof payload.slicerVersion !== "string") ||
    !isNullableHex64(payload.profileSha256) ||
    !isIsoTimestamp(payload.queuedAt) ||
    !isNullableIsoTimestamp(payload.startedAt) ||
    !isNullableIsoTimestamp(payload.completedAt) ||
    (payload.failureCode !== null && typeof payload.failureCode !== "string") ||
    !Array.isArray(payload.assets)
  ) {
    throw new QuoteApiError("The quote service returned an invalid analysis response.", 502);
  }
  return {
    id: payload.id,
    requestVersion: payload.requestVersion,
    status: payload.status as AnalysisRunStatus,
    attemptCount: payload.attemptCount,
    validatorVersion: payload.validatorVersion,
    slicerName: payload.slicerName as string | null,
    slicerVersion: payload.slicerVersion as string | null,
    profileSha256: payload.profileSha256 as string | null,
    queuedAt: payload.queuedAt,
    startedAt: payload.startedAt as string | null,
    completedAt: payload.completedAt as string | null,
    failureCode: payload.failureCode as string | null,
    assets: payload.assets.map(parseAnalysisAssetResult),
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
    !Array.isArray(payload.assets) ||
    (payload.latestAnalysis !== null && !isRecord(payload.latestAnalysis))
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
    latestAnalysis:
      payload.latestAnalysis === null ? null : parseAnalysisRun(payload.latestAnalysis),
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
