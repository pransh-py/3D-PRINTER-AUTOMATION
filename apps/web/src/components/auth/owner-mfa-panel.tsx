"use client";

import { type FormEvent, useEffect, useState } from "react";

import {
  AuthApiError,
  type OwnerMfaEnrollment,
  confirmOwnerMfaEnrollment,
  getOwnerMfaStatus,
  startOwnerMfaEnrollment,
} from "@/lib/auth-api";

import styles from "./auth-form.module.css";

export function OwnerMfaPanel() {
  const [loading, setLoading] = useState(true);
  const [enabled, setEnabled] = useState(false);
  const [pending, setPending] = useState(false);
  const [enrollment, setEnrollment] = useState<OwnerMfaEnrollment | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<readonly string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void getOwnerMfaStatus()
      .then((status) => {
        if (active) {
          setEnabled(status);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(
            caught instanceof AuthApiError
              ? caught.message
              : "Owner MFA status could not be loaded.",
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

  async function handleStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const result = await startOwnerMfaEnrollment(
        String(data.get("current-password") ?? ""),
        document.cookie,
      );
      form.reset();
      setEnrollment(result);
    } catch (caught) {
      setError(
        caught instanceof AuthApiError
          ? caught.message
          : "Owner MFA enrollment could not be started.",
      );
    } finally {
      setPending(false);
    }
  }

  async function handleConfirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    const data = new FormData(event.currentTarget);
    try {
      const result = await confirmOwnerMfaEnrollment(
        String(data.get("mfa-code") ?? ""),
        document.cookie,
      );
      setEnrollment(null);
      setEnabled(true);
      setRecoveryCodes(result.recoveryCodes);
    } catch (caught) {
      setError(
        caught instanceof AuthApiError
          ? caught.message
          : "Owner MFA could not be confirmed.",
      );
    } finally {
      setPending(false);
    }
  }

  if (loading) {
    return <p className={styles.status}>Checking owner MFA…</p>;
  }

  if (recoveryCodes !== null) {
    return (
      <section className={styles.securityPanel} aria-live="polite">
        <p className={styles.success}>Owner MFA is enabled.</p>
        <div className={styles.recoveryNotice}>
          <h3>Save these recovery codes now</h3>
          <p>Each code works once. They will not be shown again.</p>
          <ul className={styles.recoveryCodes}>
            {recoveryCodes.map((code) => (
              <li key={code}>
                <code>{code}</code>
              </li>
            ))}
          </ul>
        </div>
      </section>
    );
  }

  if (enabled) {
    return (
      <section className={styles.securityPanel}>
        <h2>Owner security</h2>
        <p className={styles.success}>Authenticator MFA is enabled for this owner.</p>
        <p className={styles.help}>
          Sensitive payment, pricing, and printer actions will require recent owner MFA.
        </p>
      </section>
    );
  }

  return (
    <section className={styles.securityPanel}>
      <h2>Secure the owner account</h2>
      <p className={styles.help}>
        Owner MFA must be enabled before payment verification or printer controls can launch.
      </p>
      {enrollment === null ? (
        <form className={styles.form} onSubmit={handleStart}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="current-password">
              Current password
            </label>
            <input
              className={styles.input}
              id="current-password"
              name="current-password"
              type="password"
              autoComplete="current-password"
              maxLength={1024}
              required
              disabled={pending}
            />
          </div>
          <button className={styles.submit} type="submit" disabled={pending}>
            {pending ? "Preparing MFA…" : "Set up authenticator MFA"}
          </button>
        </form>
      ) : (
        <div className={styles.form}>
          <div className={styles.enrollmentSecret}>
            <p>Add this setup key to your authenticator app:</p>
            <code>{enrollment.secret}</code>
            <a className={styles.inlineLink} href={enrollment.provisioningUri}>
              Open in an authenticator app
            </a>
          </div>
          <form className={styles.form} onSubmit={handleConfirm}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="owner-mfa-code">
                Six-digit code
              </label>
              <input
                className={styles.input}
                id="owner-mfa-code"
                name="mfa-code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                minLength={6}
                maxLength={6}
                required
                disabled={pending}
              />
            </div>
            <button className={styles.submit} type="submit" disabled={pending}>
              {pending ? "Confirming…" : "Confirm and enable MFA"}
            </button>
          </form>
        </div>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
