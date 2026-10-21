"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  buyerNextSteps,
  getBuyerDashboard,
  totalStates,
  type BuyerDashboard,
} from "@/lib/dashboard-api";
import { listQuoteRequests, type QuoteRequest } from "@/lib/quote-api";
import { formatMoney, type Order } from "@/lib/workflow-api";
import styles from "./dashboard.module.css";
import { StatusBadge } from "@/components/status-badge";

export function BuyerOverview({
  refreshKey,
  name,
  orders,
  selectTab,
  openOrder,
}: {
  refreshKey: number;
  name: string;
  orders: readonly Order[];
  selectTab(tab: string, filter?: string): void;
  openOrder(id: string): Promise<void>;
}) {
  const [data, setData] = useState<BuyerDashboard | null>(null);
  const [requests, setRequests] = useState<readonly QuoteRequest[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void Promise.all([getBuyerDashboard(), listQuoteRequests(5)])
      .then(([summary, rows]) => {
        if (active) {
          setData(summary);
          setRequests(rows.items);
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setData(null);
          setRequests([]);
          setError(
            caught instanceof Error
              ? caught.message
              : "Your printing summary could not be loaded.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [refreshKey]);

  if (error)
    return (
      <p role="alert" className={styles.error}>
        {error} Use Refresh to try again.
      </p>
    );
  if (!data) return <p role="status">Loading your printing overview…</p>;
  const steps = buyerNextSteps(data);

  return (
    <section className={styles.overview} aria-label="Buyer overview">
      <div className={styles.welcome}>
        <div>
          <p className={styles.kicker}>YOUR PRINTING DESK</p>
          <h2>Welcome back, {name}.</h2>
        </div>
        <Link className={styles.primary} href="/get-a-quote">
          Start a print request <span aria-hidden="true">↗</span>
        </Link>
      </div>
      {!data.payments.onlineEnabled || data.payments.testMode ? (
        <div className={styles.info}>
          {data.payments.testMode
            ? "Test checkout only. No real money is collected."
            : "Online payment isn’t available yet. Accepted quotations stay saved until you can pay."}
        </div>
      ) : null}
      {totalStates(data.quoteRequests) === 0 &&
      totalStates(data.orders) === 0 ? (
        <div className={styles.empty}>
          <p className={styles.kicker}>FROM FILE TO FINISHED PART</p>
          <h3>No requests yet.</h3>
          <p>
            Upload a model, choose your print requirements and receive a
            reviewed quotation. Your requests and progress will appear here.
          </p>
          <Link href="/get-a-quote">Upload your first model →</Link>
        </div>
      ) : null}
      <div className={styles.metrics}>
        <button onClick={() => selectTab("quotations", "actionable")}>
          <span>Ready to review</span>
          <strong>{steps.quotations}</strong>
          <small>Valid final quotations ↗</small>
        </button>
        <button onClick={() => selectTab("orders", "payment_due")}>
          <span>Payment due</span>
          <strong>{steps.paymentDue}</strong>
          <small>Accepted orders awaiting payment ↗</small>
        </button>
        <button onClick={() => selectTab("orders", "production")}>
          <span>In production</span>
          <strong>{steps.production}</strong>
          <small>Paid, queued or being made ↗</small>
        </button>
        <button onClick={() => selectTab("orders", "handover")}>
          <span>Ready / on the way</span>
          <strong>{steps.handover}</strong>
          <small>Pickup, delivery or shipping ↗</small>
        </button>
      </div>
      {steps.paymentProcessing > 0 ? (
        <p className={styles.warning}>
          {steps.paymentProcessing} payment(s) are being checked. Open your
          order to check status; don’t pay again while an attempt is unresolved.
        </p>
      ) : null}
      {steps.needsAttention > 0 ? (
        <p className={styles.warning}>
          {steps.needsAttention} order(s) need review.{" "}
          <button onClick={() => selectTab("orders", "attention")}>
            View order details →
          </button>
        </p>
      ) : null}
      <div className={styles.columns}>
        <section className={styles.panel} aria-labelledby="buyer-orders">
          <div className={styles.panelHeading}>
            <h3 id="buyer-orders">Your latest orders</h3>
            <button onClick={() => selectTab("orders", "all")}>
              All orders →
            </button>
          </div>
          {orders.length === 0 ? (
            <p className={styles.panelEmpty}>
              Your first order appears here after you accept a quotation.
            </p>
          ) : (
            <div className={styles.orderRows}>
              {orders.slice(0, 5).map((order) => (
                <button key={order.id} onClick={() => void openOrder(order.id)}>
                  <span>
                    <strong>{order.publicReference}</strong>
                    <small>
                      <StatusBadge kind="order" status={order.status} /> ·{" "}
                      {new Date(order.acceptedAt).toLocaleDateString("en-IN")}
                    </small>
                  </span>
                  <span>
                    {formatMoney(order.amountPaise)}{" "}
                    <span aria-hidden="true">↗</span>
                  </span>
                </button>
              ))}
            </div>
          )}
          <p className={styles.panelFootnote}>
            {steps.completed} completed order(s) · {totalStates(data.orders)}{" "}
            accepted in total
          </p>
        </section>
        <section className={styles.panel} aria-labelledby="buyer-requests">
          <div className={styles.panelHeading}>
            <h3 id="buyer-requests">Your model requests</h3>
            <Link href="/get-a-quote">Upload models →</Link>
          </div>
          <div className={styles.requestSummary}>
            <span>
              <strong>{steps.drafts}</strong> drafts
            </span>
            <span>
              <strong>{steps.awaitingOwner}</strong> in analysis / review
            </span>
            <span>
              <strong>{steps.analysisFailed}</strong> analysis failed
            </span>
          </div>
          {requests.length === 0 ? (
            <p className={styles.panelEmpty}>
              Your private model requests will appear here.
            </p>
          ) : (
            <ul className={styles.records}>
              {requests.map((row) => (
                <li key={row.id}>
                  <div>
                    <strong>
                      <Link href={`/get-a-quote#request-${row.id}`}>
                        {row.assets.map((asset) => asset.filename).join(", ") ||
                          `Request ${row.id.slice(0, 8)}`}
                      </Link>
                    </strong>
                    <small>
                      {row.quantity} {row.quantity === 1 ? "copy" : "copies"} ·{" "}
                      {row.fulfillmentMode.replaceAll("_", " ")}
                    </small>
                  </div>
                  <StatusBadge kind="request" status={row.status} />
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <ol className={styles.process} aria-label="How your print order works">
        <li>
          <span>01</span>
          <strong>Upload & configure</strong>
          <p>Your models stay private.</p>
        </li>
        <li>
          <span>02</span>
          <strong>Review a quotation</strong>
          <p>Accept the final price.</p>
        </li>
        <li>
          <span>03</span>
          <strong>Pay & follow progress</strong>
          <p>Printing starts after payment.</p>
        </li>
        <li>
          <span>04</span>
          <strong>Collect or receive</strong>
          <p>Quality checks come before handover.</p>
        </li>
      </ol>
      <p className={styles.footnote}>
        Updated{" "}
        {new Date(data.generatedAt).toLocaleTimeString("en-IN", {
          hour: "2-digit",
          minute: "2-digit",
        })}
        .
      </p>
    </section>
  );
}
