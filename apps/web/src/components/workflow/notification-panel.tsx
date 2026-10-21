"use client";

import { useEffect, useState } from "react";
import { listNotifications, retryNotification, type NotificationSummary } from "@/lib/workflow-api";
import styles from "./workflow.module.css";

export function NotificationPanel() {
  const [rows, setRows] = useState<readonly NotificationSummary[]>([]);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void listNotifications().then((value) => {
      if (active) { setRows(value.items); setEnabled(value.enabled); }
    }).catch((caught: unknown) => {
      if (active) setError(caught instanceof Error ? caught.message : "Could not load notices.");
    });
    return () => { active = false; };
  }, []);
  async function refresh(id?: string) {
    setBusy(true);
    setError(null);
    try {
      if (id) await retryNotification(id);
      const value = await listNotifications();
      setRows(value.items); setEnabled(value.enabled);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update notices.");
    } finally { setBusy(false); }
  }
  return (
    <section aria-label="Notification delivery">
      <h2>Email delivery</h2>
      <p>Emails contain a status update and sign-in link, never model or payment details. “Sent” means our mail server accepted it.</p>
      {enabled === false ? <p className={styles.boundary}>Status emails are turned off. Set up and approve a sender to turn them on. Sign-in and password emails are separate.</p> : null}
      <button disabled={busy} onClick={() => void refresh()}>Refresh notices</button>
      {error ? <p role="alert" className={styles.error}>{error}</p> : null}
      {enabled !== null && rows.length === 0 ? <p>No delivery records yet.</p> : null}
      {rows.map((row) => (
        <article className={styles.card} key={row.id}>
          <h3>{row.templateCode.replaceAll(".", " · ").replaceAll("_", " ")}</h3>
          <p>{row.status.replaceAll("_", " ")} · Attempts: {row.attemptCount}</p>
          {row.lastErrorCode ? <p>Needs attention: {row.lastErrorCode.replaceAll("_", " ")}</p> : null}
          {row.sentAt ? <p>Accepted: {new Date(row.sentAt).toLocaleString("en-IN")}</p> : null}
          {row.status === "dead_lettered" ? <button disabled={busy || !enabled} onClick={() => void refresh(row.id)}>Retry (recent MFA)</button> : null}
        </article>
      ))}
    </section>
  );
}
