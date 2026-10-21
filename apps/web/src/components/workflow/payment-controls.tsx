"use client";

import Script from "next/script";
import { useEffect, useRef, useState } from "react";
import {
  createCheckout,
  reconcilePayment,
  returnCheckout,
  formatMoney,
  type Checkout,
  type OrderDetail,
} from "@/lib/workflow-api";
import styles from "./workflow.module.css";

type CheckoutResponse = {
  razorpay_payment_id: string;
  razorpay_order_id: string;
  razorpay_signature: string;
};
type Popup = {
  open(): void;
  close(): void;
  on(event: "payment.failed", callback: () => void): void;
};
type RazorpayConstructor = new (options: {
  key: string;
  order_id: string;
  amount: number;
  currency: "INR";
  name: string;
  handler(response: CheckoutResponse): void;
  modal: { ondismiss(): void };
}) => Popup;

export function PaymentControls({
  order,
  owner,
  busy,
  run,
}: {
  order: OrderDetail;
  owner: boolean;
  busy: boolean;
  run(work: () => Promise<unknown>): Promise<void>;
}) {
  const [checkout, setCheckout] = useState<Checkout | null>(null);
  const [ready, setReady] = useState(false);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const popup = useRef<Popup | null>(null);
  const enabled = order.payment.checkoutEnabled;
  // The parent's refresh closure changes on renders; it must not reopen a payment modal.
  const runRef = useRef(run);
  useEffect(() => {
    runRef.current = run;
  }, [run]);

  useEffect(() => {
    if (!ready || !checkout || popup.current) return;
    const Constructor = (window as Window & { Razorpay?: RazorpayConstructor })
      .Razorpay;
    if (!Constructor) return;
    const instance = new Constructor({
      key: checkout.keyId,
      order_id: checkout.providerOrderId,
      amount: checkout.amountPaise,
      currency: checkout.currency,
      name: checkout.displayName,
      handler: (response) => {
        instance.close();
        // No client paid state: record feedback, then await server confirmation.
        void runRef.current(() => returnCheckout(order.id, response));
      },
      modal: {
        ondismiss: () => {
          popup.current = null;
          setCheckout(null);
          setOpening(false);
        },
      },
    });
    popup.current = instance;
    instance.on("payment.failed", () =>
      setError("Payment did not complete. Check its status before retrying."),
    );
    instance.open();
    return () => {
      instance.close();
      popup.current = null;
    };
  }, [ready, checkout, order.id]);

  async function pay() {
    setOpening(true);
    setError(null);
    try {
      const value = await createCheckout(order.id);
      if (
        value.amountPaise !== order.amountPaise ||
        value.testMode !== order.payment.testMode
      )
        throw new Error("Payment details changed. Refresh before paying.");
      setCheckout(value);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not open payment.",
      );
      setOpening(false);
    }
  }

  return (
    <section aria-label="Payment">
      <p className={styles.boundary}>{order.payment.message}</p>
      {error ? (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      ) : null}
      {checkout ? (
        <Script
          src="https://checkout.razorpay.com/v1/checkout.js"
          onReady={() => setReady(true)}
          onError={() => {
            setError(
              "Checkout could not load. Reload the page to retry, or check payment status.",
            );
            setOpening(false);
          }}
        />
      ) : null}
      <div className={styles.actions}>
        {!owner &&
        enabled &&
        ["payment_pending", "payment_failed"].includes(order.status) ? (
          <button disabled={busy || opening} onClick={() => void pay()}>
            {opening
              ? "Opening secure Checkout…"
              : `${order.payment.testMode ? "Test payment" : "Pay"} ${formatMoney(order.amountPaise)}`}
          </button>
        ) : null}
        {enabled ? (
          <button
            disabled={busy || opening}
            onClick={() => void run(() => reconcilePayment(order.id, owner))}
          >
            {owner
              ? "Reconcile with Razorpay (recent MFA)"
              : "Check payment status"}
          </button>
        ) : null}
      </div>
      {enabled ? (
        <p>
          After paying, check payment status. If confirmation is delayed,
          don’t pay again.
        </p>
      ) : null}
    </section>
  );
}
