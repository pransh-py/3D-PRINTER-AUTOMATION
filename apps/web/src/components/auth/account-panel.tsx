"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  AuthApiError,
  type AuthenticatedUser,
  getCurrentUserWithRefresh,
  logoutSession,
} from "@/lib/auth-api";

import styles from "./auth-form.module.css";
import { OwnerMfaPanel } from "./owner-mfa-panel";

export function AccountPanel() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [loggingOut, setLoggingOut] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void getCurrentUserWithRefresh(document.cookie)
      .then((currentUser) => {
        if (active) {
          setUser(currentUser);
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(
            caught instanceof AuthApiError
              ? caught.message
              : "Your account could not be loaded.",
          );
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function handleLogout() {
    setLoggingOut(true);
    setError(null);
    try {
      await logoutSession(document.cookie);
      window.location.assign("/sign-in");
    } catch (caught) {
      setError(
        caught instanceof AuthApiError ? caught.message : "Sign-out could not be completed.",
      );
      setLoggingOut(false);
    }
  }

  if (loading) {
    return <p className={styles.status}>Loading your protected account…</p>;
  }

  if (user === null) {
    return (
      <div className={styles.result}>
        <p className={styles.error} role="alert">
          {error ?? "Please sign in to view this page."}
        </p>
        <Link className={styles.submitLink} href="/sign-in">
          Go to sign in
        </Link>
      </div>
    );
  }

  return (
    <div className={styles.form}>
      <dl className={styles.accountDetails}>
        <div>
          <dt>Name</dt>
          <dd>{user.displayName}</dd>
        </div>
        <div>
          <dt>Email</dt>
          <dd>{user.email}</dd>
        </div>
        <div>
          <dt>Role</dt>
          <dd>{user.role === "owner" ? "Business owner" : "Buyer"}</dd>
        </div>
      </dl>
      <p className={styles.help}>
        Model uploads, quotes, and order tracking will appear here in the next product phase.
      </p>
      {user.role === "owner" && <OwnerMfaPanel />}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <button className={styles.submit} type="button" onClick={handleLogout} disabled={loggingOut}>
        {loggingOut ? "Signing out…" : "Sign out"}
      </button>
    </div>
  );
}
