const AUTH_API_BASE = "/api/v1/auth";

export type AuthenticatedUser = Readonly<{
  id: string;
  email: string;
  displayName: string;
  role: "buyer" | "owner";
}>;

type MessageResponse = Readonly<{ message: string }>;

export type LoginResult =
  | Readonly<{ kind: "authenticated"; user: AuthenticatedUser }>
  | Readonly<{ kind: "mfa_required"; challenge: string }>;

export type OwnerMfaEnrollment = Readonly<{
  secret: string;
  provisioningUri: string;
}>;

export type OwnerMfaConfirmation = Readonly<{
  message: string;
  recoveryCodes: readonly string[];
}>;

let currentUserRequest: Promise<AuthenticatedUser> | null = null;

export class AuthApiError extends Error {
  readonly status: number;
  readonly retryAfterSeconds: number | null;

  constructor(message: string, status: number, retryAfterSeconds: number | null = null) {
    super(message);
    this.name = "AuthApiError";
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

function authenticatedUser(payload: unknown): AuthenticatedUser {
  if (
    !isRecord(payload) ||
    typeof payload.id !== "string" ||
    typeof payload.email !== "string" ||
    typeof payload.displayName !== "string" ||
    (payload.role !== "buyer" && payload.role !== "owner")
  ) {
    throw new AuthApiError("The account service returned an invalid response.", 502);
  }
  return {
    id: payload.id,
    email: payload.email,
    displayName: payload.displayName,
    role: payload.role,
  };
}

function csrfToken(cookieString: string): string {
  const token = readCsrfCookie(cookieString);
  if (token === null) {
    throw new AuthApiError("Your session has expired. Please sign in again.", 401);
  }
  return token;
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

async function request<T>(
  path: string,
  init: Readonly<{
    method?: "GET" | "POST";
    body?: unknown;
    csrfToken?: string;
  }> = {},
): Promise<T> {
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
    response = await fetch(`${AUTH_API_BASE}${path}`, {
      method: init.method ?? "GET",
      headers,
      body,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new AuthApiError("The account service is unavailable. Please try again.", 0);
  }

  if (!response.ok) {
    const payload = await readPayload(response);
    throw new AuthApiError(
      responseMessage(payload, "The account request could not be completed."),
      response.status,
      parseRetryAfter(response),
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }
  const payload = await readPayload(response);
  if (payload === null) {
    throw new AuthApiError("The account service returned an invalid response.", 502);
  }
  return payload as T;
}

export function readCsrfCookie(cookieString: string): string | null {
  const acceptedNames = new Set(["xxx_csrf", "__Host-xxx_csrf"]);
  for (const entry of cookieString.split(";")) {
    const separator = entry.indexOf("=");
    if (separator === -1) {
      continue;
    }
    const name = entry.slice(0, separator).trim();
    if (!acceptedNames.has(name)) {
      continue;
    }
    const value = entry.slice(separator + 1);
    try {
      return decodeURIComponent(value);
    } catch {
      return null;
    }
  }
  return null;
}

export function extractFragmentToken(fragment: string): string | null {
  const parameters = new URLSearchParams(fragment.startsWith("#") ? fragment.slice(1) : fragment);
  const token = parameters.get("token");
  return token && token.length > 0 ? token : null;
}

export function fragmentlessLocation(pathname: string, search: string): string {
  return `${pathname}${search}`;
}

export async function registerBuyer(input: {
  email: string;
  displayName: string;
  password: string;
}): Promise<MessageResponse> {
  return request<MessageResponse>("/register", { method: "POST", body: input });
}

export async function loginBuyer(input: {
  email: string;
  password: string;
}): Promise<LoginResult> {
  const payload = await request<unknown>("/login", { method: "POST", body: input });
  if (
    isRecord(payload) &&
    payload.mfaRequired === true &&
    typeof payload.challenge === "string" &&
    payload.challenge.length > 0
  ) {
    return { kind: "mfa_required", challenge: payload.challenge };
  }
  return { kind: "authenticated", user: authenticatedUser(payload) };
}

export async function completeMfaLogin(challenge: string, code: string): Promise<AuthenticatedUser> {
  return authenticatedUser(
    await request<unknown>("/login/mfa", {
      method: "POST",
      body: { challenge, code },
    }),
  );
}

export async function requestPasswordReset(email: string): Promise<MessageResponse> {
  return request<MessageResponse>("/forgot-password", {
    method: "POST",
    body: { email },
  });
}

export async function resendVerification(email: string): Promise<MessageResponse> {
  return request<MessageResponse>("/resend-verification", {
    method: "POST",
    body: { email },
  });
}

export async function verifyEmail(token: string): Promise<MessageResponse> {
  return request<MessageResponse>("/verify-email", {
    method: "POST",
    body: { token },
  });
}

export async function resetPassword(token: string, newPassword: string): Promise<MessageResponse> {
  return request<MessageResponse>("/reset-password", {
    method: "POST",
    body: { token, newPassword },
  });
}

export async function getCurrentUser(): Promise<AuthenticatedUser> {
  return authenticatedUser(await request<unknown>("/me"));
}

export async function refreshSession(cookieString: string): Promise<void> {
  await request<void>("/refresh", { method: "POST", csrfToken: csrfToken(cookieString) });
}

async function loadCurrentUserWithRefresh(cookieString: string): Promise<AuthenticatedUser> {
  try {
    return await getCurrentUser();
  } catch (error) {
    if (!(error instanceof AuthApiError) || error.status !== 401) {
      throw error;
    }
  }
  await refreshSession(cookieString);
  return getCurrentUser();
}

export function getCurrentUserWithRefresh(cookieString: string): Promise<AuthenticatedUser> {
  if (currentUserRequest !== null) {
    return currentUserRequest;
  }
  const requestPromise = loadCurrentUserWithRefresh(cookieString);
  currentUserRequest = requestPromise;
  const clearRequest = () => {
    if (currentUserRequest === requestPromise) {
      currentUserRequest = null;
    }
  };
  void requestPromise.then(clearRequest, clearRequest);
  return requestPromise;
}

export async function logoutSession(cookieString: string): Promise<void> {
  await request<void>("/logout", { method: "POST", csrfToken: csrfToken(cookieString) });
}

export async function getOwnerMfaStatus(): Promise<boolean> {
  const payload = await request<unknown>("/mfa");
  if (!isRecord(payload) || typeof payload.enabled !== "boolean") {
    throw new AuthApiError("The account service returned an invalid response.", 502);
  }
  return payload.enabled;
}

export async function startOwnerMfaEnrollment(
  currentPassword: string,
  cookieString: string,
): Promise<OwnerMfaEnrollment> {
  const payload = await request<unknown>("/mfa/totp/enroll", {
    method: "POST",
    csrfToken: csrfToken(cookieString),
    body: { currentPassword },
  });
  if (
    !isRecord(payload) ||
    typeof payload.secret !== "string" ||
    typeof payload.provisioningUri !== "string"
  ) {
    throw new AuthApiError("The account service returned an invalid response.", 502);
  }
  return { secret: payload.secret, provisioningUri: payload.provisioningUri };
}

export async function confirmOwnerMfaEnrollment(
  code: string,
  cookieString: string,
): Promise<OwnerMfaConfirmation> {
  const payload = await request<unknown>("/mfa/totp/confirm", {
    method: "POST",
    csrfToken: csrfToken(cookieString),
    body: { code },
  });
  if (
    !isRecord(payload) ||
    typeof payload.message !== "string" ||
    !Array.isArray(payload.recoveryCodes) ||
    !payload.recoveryCodes.every((item) => typeof item === "string")
  ) {
    throw new AuthApiError("The account service returned an invalid response.", 502);
  }
  return { message: payload.message, recoveryCodes: payload.recoveryCodes };
}
