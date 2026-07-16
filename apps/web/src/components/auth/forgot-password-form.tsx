"use client";

import { type FormEvent, useState } from "react";

import { AuthApiError, requestPasswordReset } from "@/lib/auth-api";

import styles from "./auth-form.module.css";

export function ForgotPasswordForm() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [complete, setComplete] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setComplete(false);
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await requestPasswordReset(String(data.get("email") ?? ""));
      form.reset();
      setComplete(true);
    } catch (caught) {
      setError(
        caught instanceof AuthApiError
          ? caught.message
          : "Reset instructions could not be requested. Please try again.",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.field}>
        <label className={styles.label} htmlFor="email">
          Email
        </label>
        <input
          className={styles.input}
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          autoCapitalize="none"
          spellCheck={false}
          placeholder="you@example.com"
          required
          disabled={pending}
        />
      </div>
      {complete && (
        <p className={styles.success} aria-live="polite">
          If the account is eligible, reset instructions are on the way.
        </p>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <button className={styles.submit} type="submit" disabled={pending}>
        {pending ? "Requesting…" : complete ? "Send again" : "Send reset link"}
      </button>
    </form>
  );
}
