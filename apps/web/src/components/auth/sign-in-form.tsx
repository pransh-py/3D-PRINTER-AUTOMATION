"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { AuthApiError, completeMfaLogin, loginBuyer } from "@/lib/auth-api";

import styles from "./auth-form.module.css";

export function SignInForm() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [challenge, setChallenge] = useState<string | null>(null);

  async function handlePasswordSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    const data = new FormData(event.currentTarget);

    try {
      const result = await loginBuyer({
        email: String(data.get("email") ?? ""),
        password: String(data.get("password") ?? ""),
      });
      if (result.kind === "mfa_required") {
        setChallenge(result.challenge);
        setPending(false);
        return;
      }
      router.replace("/account");
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof AuthApiError
          ? caught.message
          : "Sign-in could not be completed. Please try again.",
      );
      setPending(false);
    }
  }

  async function handleMfaSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (challenge === null) {
      return;
    }
    setPending(true);
    setError(null);
    const data = new FormData(event.currentTarget);
    try {
      await completeMfaLogin(challenge, String(data.get("code") ?? ""));
      setChallenge(null);
      router.replace("/account");
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof AuthApiError
          ? caught.message
          : "MFA verification could not be completed. Please try again.",
      );
      setPending(false);
    }
  }

  if (challenge !== null) {
    return (
      <form className={styles.form} onSubmit={handleMfaSubmit}>
        <p className={styles.status}>
          Enter the six-digit code from the owner authenticator, or one unused recovery code.
        </p>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="mfa-code">
            Authentication code
          </label>
          <input
            className={styles.input}
            id="mfa-code"
            name="code"
            type="text"
            autoComplete="one-time-code"
            autoCapitalize="characters"
            spellCheck={false}
            minLength={6}
            maxLength={64}
            required
            autoFocus
            disabled={pending}
          />
        </div>
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
        <button className={styles.submit} type="submit" disabled={pending}>
          {pending ? "Verifying…" : "Verify and sign in"}
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={() => {
            setChallenge(null);
            setError(null);
          }}
          disabled={pending}
        >
          Start over
        </button>
      </form>
    );
  }

  return (
    <form className={styles.form} onSubmit={handlePasswordSubmit}>
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
          autoComplete="current-password"
          placeholder="Your password"
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
      <div className={styles.submitRow}>
        <button className={styles.submit} type="submit" disabled={pending}>
          {pending ? "Signing in…" : "Sign in"}
        </button>
        <Link className={styles.inlineLink} href="/forgot-password">
          Forgot your password?
        </Link>
      </div>
    </form>
  );
}
