"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useRef, useState } from "react";

import {
  AuthApiError,
  extractFragmentToken,
  fragmentlessLocation,
  resetPassword,
} from "@/lib/auth-api";

import styles from "./auth-form.module.css";

export function ResetPasswordForm() {
  const initialized = useRef(false);
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [pending, setPending] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialized.current) {
      return;
    }
    initialized.current = true;
    const fragmentToken = extractFragmentToken(window.location.hash);
    window.history.replaceState(
      window.history.state,
      "",
      fragmentlessLocation(window.location.pathname, window.location.search),
    );
    queueMicrotask(() => {
      setToken(fragmentToken);
      setReady(true);
      if (fragmentToken === null) {
        setError("This reset link is missing its secure token. Request a new link.");
      }
    });
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (token === null) {
      setError("This reset link cannot be used. Request a new link.");
      return;
    }
    const data = new FormData(event.currentTarget);
    const password = String(data.get("new-password") ?? "");
    const confirmation = String(data.get("confirm-new-password") ?? "");
    if (password !== confirmation) {
      setError("The passwords do not match.");
      return;
    }

    setPending(true);
    setError(null);
    try {
      await resetPassword(token, password);
      setToken(null);
      setComplete(true);
    } catch (caught) {
      setError(
        caught instanceof AuthApiError
          ? caught.message
          : "Your password could not be reset. Please try again.",
      );
    } finally {
      setPending(false);
    }
  }

  if (!ready) {
    return <p className={styles.status}>Checking your reset link…</p>;
  }

  if (complete) {
    return (
      <div className={styles.result} aria-live="polite">
        <p className={styles.success}>Your password has been reset and existing sessions were signed out.</p>
        <Link className={styles.submitLink} href="/sign-in">
          Sign in with the new password
        </Link>
      </div>
    );
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.field}>
        <label className={styles.label} htmlFor="new-password">
          New password
        </label>
        <input
          className={styles.input}
          id="new-password"
          name="new-password"
          type="password"
          autoComplete="new-password"
          placeholder="At least 12 characters"
          minLength={12}
          maxLength={1024}
          required
          disabled={pending || token === null}
        />
      </div>
      <div className={styles.field}>
        <label className={styles.label} htmlFor="confirm-new-password">
          Confirm new password
        </label>
        <input
          className={styles.input}
          id="confirm-new-password"
          name="confirm-new-password"
          type="password"
          autoComplete="new-password"
          placeholder="Re-enter your new password"
          minLength={12}
          maxLength={1024}
          required
          disabled={pending || token === null}
        />
      </div>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <button className={styles.submit} type="submit" disabled={pending || token === null}>
        {pending ? "Resetting password…" : "Reset password"}
      </button>
      {token === null && (
        <Link className={styles.inlineLink} href="/forgot-password">
          Request a new reset link
        </Link>
      )}
    </form>
  );
}
