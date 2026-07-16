"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { AuthApiError, loginBuyer } from "@/lib/auth-api";

import styles from "./auth-form.module.css";

export function SignInForm() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    const data = new FormData(event.currentTarget);

    try {
      await loginBuyer({
        email: String(data.get("email") ?? ""),
        password: String(data.get("password") ?? ""),
      });
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
