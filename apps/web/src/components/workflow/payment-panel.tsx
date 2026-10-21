"use client";

import { useEffect, useState } from "react";
import {
  formatMoney,
  listPayments,
  reconcilePayment,
  type PaymentSummary,
} from "@/lib/workflow-api";
import styles from "./workflow.module.css";

export function PaymentPanel({
  openOrder,
}: {
  openOrder(id: string): Promise<void>;
}) {
  const [rows, setRows] = useState<readonly PaymentSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void listPayments()
      .then((value) => {
        if (active) setRows(value);
      })
      .catch((caught: unknown) => {
        if (active)
          setError(
            caught instanceof Error
              ? caught.message
              : "Could not load payments.",
          );
      });
    return () => {
      active = false;
    };
  }, []);
  async function refresh(id?: string) {
    setBusy(true);
    setError(null);
    try {
      if (id) await reconcilePayment(id, true);
      setRows(await listPayments());
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Payment check failed.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="Payment exceptions">
      <h2>Payments & reconciliation</h2>
      <p>
        Payments are confirmed by Razorpay. Orders can’t be marked paid manually,
        and refunds and manual UPI aren’t available yet.
      </p>
      <button disabled={busy} onClick={() => void refresh()}>
        Refresh payments
      </button>
      {error ? (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      ) : null}
      {rows.length === 0 ? (
        <p>No payment instructions have been created.</p>
      ) : null}
      {rows.map((row) => (
        <article className={styles.card} key={row.id}>
          <h3>
            {row.publicReference} · {formatMoney(row.amountPaise)}
          </h3>
          {row.testMode ? (
            <p className={styles.boundary}>
              Test environment. Not a real payment or print.
            </p>
          ) : null}
          <p>
            {row.status.replaceAll("_", " ")} · Order:{" "}
            {row.orderStatus.replaceAll("_", " ")}
          </p>
          {row.failureCode ? (
            <p role="status">
              Needs attention: {row.failureCode.replaceAll("_", " ")}
            </p>
          ) : null}
          <p>
            Last checked:{" "}
            {row.lastReconciledAt
              ? new Date(row.lastReconciledAt).toLocaleString("en-IN")
              : "Not yet"}
          </p>
          <div className={styles.actions}>
            <button disabled={busy} onClick={() => void openOrder(row.orderId)}>
              Open order
            </button>
            {row.status !== "captured" ? (
              <button disabled={busy} onClick={() => void refresh(row.orderId)}>
                Reconcile (recent MFA)
              </button>
            ) : null}
          </div>
        </article>
      ))}
    </section>
  );
}
