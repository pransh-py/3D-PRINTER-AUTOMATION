"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useRef, useState } from "react";

import {
  AuthApiError,
  extractFragmentToken,
  fragmentlessLocation,
  resendVerification,
  verifyEmail,
} from "@/lib/auth-api";

import styles from "./auth-form.module.css";

type VerificationState = "checking" | "missing" | "verified" | "failed";

export function VerifyEmailPanel() {
  const attempted = useRef(false);
  const [state, setState] = useState<VerificationState>("checking");
  const [message, setMessage] = useState("Checking your verification link…");
  const [resendPending, setResendPending] = useState(false);
  const [resendComplete, setResendComplete] = useState(false);
  const [resendError, setResendError] = useState<string | null>(null);

  useEffect(() => {
    if (attempted.current) {
      return;
    }
    attempted.current = true;
    const token = extractFragmentToken(window.location.hash);
    window.history.replaceState(
      window.history.state,
      "",
      fragmentlessLocation(window.location.pathname, window.location.search),
    );
    if (token === null) {
      queueMicrotask(() => {
        setState("missing");
        setMessage("Open the verification link from your email, or request a new one below.");
      });
      return;
    }

    void verifyEmail(token)
      .then(() => {
        setState("verified");
        setMessage("Your email is verified. You can now sign in.");
      })
      .catch((caught: unknown) => {
        setState("failed");
        setMessage(
          caught instanceof AuthApiError
            ? caught.message
            : "This verification link could not be used.",
        );
      });
  }, []);

  async function handleResend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setResendPending(true);
    setResendError(null);
    setResendComplete(false);
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await resendVerification(String(data.get("email") ?? ""));
      form.reset();
      setResendComplete(true);
    } catch (caught) {
      setResendError(
        caught instanceof AuthApiError
          ? caught.message
          : "A new verification link could not be requested.",
      );
    } finally {
      setResendPending(false);
    }
  }

  return (
    <div className={styles.form}>
      <p
        className={state === "verified" ? styles.success : state === "failed" ? styles.error : styles.status}
        role={state === "failed" ? "alert" : "status"}
      >
        {message}
      </p>
      {state === "verified" ? (
        <Link className={styles.submitLink} href="/sign-in">
          Continue to sign in
        </Link>
      ) : state === "checking" ? null : (
        <form className={styles.form} onSubmit={handleResend}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="resend-email">
              Email
            </label>
            <input
              className={styles.input}
              id="resend-email"
              name="email"
              type="email"
              autoComplete="email"
              autoCapitalize="none"
              spellCheck={false}
              placeholder="you@example.com"
              required
              disabled={resendPending}
            />
          </div>
          {resendComplete && (
            <p className={styles.success} aria-live="polite">
              If the account is eligible, a fresh verification link is on the way.
            </p>
          )}
          {resendError && (
            <p className={styles.error} role="alert">
              {resendError}
            </p>
          )}
          <button className={styles.submit} type="submit" disabled={resendPending}>
            {resendPending ? "Requesting…" : "Resend verification link"}
          </button>
        </form>
      )}
    </div>
  );
}
