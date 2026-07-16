"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { AuthApiError, registerBuyer } from "@/lib/auth-api";

import styles from "./auth-form.module.css";

export function SignUpForm() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [complete, setComplete] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = event.currentTarget;
    const data = new FormData(form);
    const password = String(data.get("password") ?? "");
    const confirmation = String(data.get("password-confirmation") ?? "");
    if (password !== confirmation) {
      setError("The passwords do not match.");
      return;
    }

    setPending(true);
    try {
      await registerBuyer({
        displayName: String(data.get("display-name") ?? ""),
        email: String(data.get("email") ?? ""),
        password,
      });
      form.reset();
      setComplete(true);
    } catch (caught) {
      setError(
        caught instanceof AuthApiError
          ? caught.message
          : "Account creation could not be completed. Please try again.",
      );
    } finally {
      setPending(false);
    }
  }

  if (complete) {
    return (
      <div className={styles.result} aria-live="polite">
        <p className={styles.success}>Check your inbox for a verification link.</p>
        <p className={styles.help}>
          For privacy, this message is the same whether the address is new or already
          registered. Verification links expire for your security.
        </p>
        <Link className={styles.submitLink} href="/verify-email">
          Verify or resend email
        </Link>
      </div>
    );
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.field}>
        <label className={styles.label} htmlFor="display-name">
          Display name
        </label>
        <input
          className={styles.input}
          id="display-name"
          name="display-name"
          type="text"
          autoComplete="name"
          placeholder="Your name"
          minLength={1}
          maxLength={100}
          required
          disabled={pending}
        />
      </div>
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
      <div className={styles.field}>
        <label className={styles.label} htmlFor="password">
          Password
        </label>
        <input
          className={styles.input}
          id="password"
          name="password"
          type="password"
          autoComplete="new-password"
          placeholder="At least 12 characters"
          minLength={12}
          maxLength={1024}
          required
          disabled={pending}
        />
      </div>
      <div className={styles.field}>
        <label className={styles.label} htmlFor="password-confirmation">
          Confirm password
        </label>
        <input
          className={styles.input}
          id="password-confirmation"
          name="password-confirmation"
          type="password"
          autoComplete="new-password"
          placeholder="Re-enter your password"
          minLength={12}
          maxLength={1024}
          required
          disabled={pending}
        />
      </div>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <button className={styles.submit} type="submit" disabled={pending}>
        {pending ? "Creating account…" : "Create account"}
      </button>
    </form>
  );
}
