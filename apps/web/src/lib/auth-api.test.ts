import assert from "node:assert/strict";
import test from "node:test";

import {
  extractFragmentToken,
  fragmentlessLocation,
  getCurrentUserWithRefresh,
  logoutSession,
  loginBuyer,
  readCsrfCookie,
  registerBuyer,
  startOwnerMfaEnrollment,
} from "./auth-api.ts";

test("reads development and production CSRF cookie names", () => {
  assert.equal(readCsrfCookie("other=1; xxx_csrf=signed%3Avalue"), "signed:value");
  assert.equal(
    readCsrfCookie("__Host-xxx_csrf=production-token; unrelated=value"),
    "production-token",
  );
});

test("does not accept similarly named or malformed CSRF cookies", () => {
  assert.equal(readCsrfCookie("prefix_xxx_csrf=attacker; other=value"), null);
  assert.equal(readCsrfCookie("xxx_csrf=%E0%A4%A"), null);
});

test("extracts only the token fragment parameter", () => {
  assert.equal(extractFragmentToken("#token=abc%20123&next=%2Faccount"), "abc 123");
  assert.equal(extractFragmentToken("#access_token=wrong"), null);
  assert.equal(extractFragmentToken(""), null);
});

test("builds a fragment-free browser location without dropping the query", () => {
  assert.equal(fragmentlessLocation("/reset-password", "?source=email"), "/reset-password?source=email");
});

test("sends account data as same-origin no-store JSON", async () => {
  const originalFetch = globalThis.fetch;
  let capturedUrl = "";
  let capturedInit: RequestInit | undefined;
  globalThis.fetch = async (input, init) => {
    capturedUrl = String(input);
    capturedInit = init;
    return Response.json({ message: "accepted" }, { status: 202 });
  };
  try {
    await registerBuyer({
      email: "buyer@example.com",
      displayName: "Buyer",
      password: "a secure password",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(capturedUrl, "/api/v1/auth/register");
  assert.equal(capturedInit?.method, "POST");
  assert.equal(capturedInit?.credentials, "same-origin");
  assert.equal(capturedInit?.cache, "no-store");
  assert.equal(new Headers(capturedInit?.headers).get("content-type"), "application/json");
  assert.deepEqual(JSON.parse(String(capturedInit?.body)), {
    email: "buyer@example.com",
    displayName: "Buyer",
    password: "a secure password",
  });
});

test("copies the signed CSRF cookie into the logout header", async () => {
  const originalFetch = globalThis.fetch;
  let capturedInit: RequestInit | undefined;
  globalThis.fetch = async (_input, init) => {
    capturedInit = init;
    return new Response(null, { status: 204 });
  };
  try {
    await logoutSession("other=1; xxx_csrf=signed%3Atoken");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(new Headers(capturedInit?.headers).get("x-csrf-token"), "signed:token");
});

test("coalesces concurrent current-user refresh flows", async () => {
  const originalFetch = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = async (input) => {
    const url = String(input);
    calls.push(url);
    if (url.endsWith("/refresh")) {
      return new Response(null, { status: 204 });
    }
    if (calls.filter((call) => call.endsWith("/me")).length === 1) {
      return Response.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return Response.json({
      id: "00000000-0000-0000-0000-000000000001",
      email: "buyer@example.com",
      displayName: "Buyer",
      role: "buyer",
    });
  };
  try {
    const first = getCurrentUserWithRefresh("xxx_csrf=signed-token");
    const second = getCurrentUserWithRefresh("xxx_csrf=signed-token");
    const [firstUser, secondUser] = await Promise.all([first, second]);
    assert.deepEqual(firstUser, secondUser);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(calls, [
    "/api/v1/auth/me",
    "/api/v1/auth/refresh",
    "/api/v1/auth/me",
  ]);
});

test("keeps an owner MFA challenge in the explicit login result", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    Response.json(
      { mfaRequired: true, challenge: "challenge-value-that-is-long-enough" },
      { status: 202 },
    );
  try {
    const result = await loginBuyer({
      email: "owner@example.com",
      password: "a secure password",
    });
    assert.deepEqual(result, {
      kind: "mfa_required",
      challenge: "challenge-value-that-is-long-enough",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("owner enrollment sends password JSON with session-bound CSRF", async () => {
  const originalFetch = globalThis.fetch;
  let capturedInit: RequestInit | undefined;
  globalThis.fetch = async (_input, init) => {
    capturedInit = init;
    return Response.json({
      secret: "BASE32SECRET",
      provisioningUri: "otpauth://totp/xxx:owner",
    });
  };
  try {
    await startOwnerMfaEnrollment("current password", "xxx_csrf=signed%3Atoken");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(new Headers(capturedInit?.headers).get("x-csrf-token"), "signed:token");
  assert.deepEqual(JSON.parse(String(capturedInit?.body)), {
    currentPassword: "current password",
  });
});
