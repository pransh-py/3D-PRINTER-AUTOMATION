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
import { roleHome } from "@/lib/dashboard-api";
import { OwnerMfaPanel } from "./owner-mfa-panel";

export function AccountPanel() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [loggingOut, setLoggingOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const [attempt, setAttempt] = useState(0);

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
          const signedOut =
            caught instanceof AuthApiError && caught.status === 401;
          setNeedsSignIn(signedOut);
          setError(
            signedOut
              ? "Please sign in to view your account."
              : "We couldn’t confirm your account right now. You have not been signed out.",
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
  }, [attempt]);

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
    return <p className={styles.status}>Loading your account…</p>;
  }

  if (user === null) {
    return (
      <div className={styles.result}>
        <p className={styles.error} role="alert">
          {error ?? "Please sign in to view this page."}
        </p>
        {needsSignIn ? (
          <Link className={styles.submitLink} href="/sign-in">Go to sign in</Link>
        ) : (
          <button className={styles.submit} type="button" onClick={() => {
            setLoading(true);
            setAttempt((value) => value + 1);
          }}>Try again</button>
        )}
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
        {user.email ? <div>
          <dt>Email</dt>
          <dd>{user.email}</dd>
        </div> : null}
        {user.phone ? <div>
          <dt>WhatsApp number — verified</dt>
          <dd>{user.phone}</dd>
        </div> : null}
        <div>
          <dt>Role</dt>
          <dd>{user.role === "owner" ? "Business owner" : "Buyer"}</dd>
        </div>
      </dl>
      {user.role === "owner" && <OwnerMfaPanel />}
      <Link href={roleHome(user.role)}>
        Open your dashboard
      </Link>
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
