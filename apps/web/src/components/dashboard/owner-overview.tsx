"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  getOwnerDashboard,
  ownerAttention,
  totalStates,
  type OwnerDashboard,
} from "@/lib/dashboard-api";
import type { QuoteRequest } from "@/lib/quote-api";
import { formatMoney, type Order } from "@/lib/workflow-api";
import styles from "./dashboard.module.css";
import { StatusBadge } from "@/components/status-badge";

export function OwnerOverview({
  refreshKey,
  requests,
  orders,
  selectTab,
  openOrder,
}: {
  refreshKey: number;
  requests: readonly QuoteRequest[];
  orders: readonly Order[];
  selectTab(tab: string, filter?: string): void;
  openOrder(id: string): Promise<void>;
}) {
  const [data, setData] = useState<OwnerDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void getOwnerDashboard()
      .then((result) => {
        if (active) {
          setData(result);
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setData(null);
          setError(
            caught instanceof Error
              ? caught.message
              : "The business summary could not be loaded.",
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
  if (!data) return <p role="status">Loading your business overview…</p>;
  const counts = ownerAttention(data);
  const tasks = [
    {
      title: "Ready to quote",
      detail: "Estimates awaiting your decision",
      count: counts.readyToQuote,
      tab: "requests",
      filter: "to_quote",
    },
    {
      title: "Analysis needs attention",
      detail: "Review rejected or failed analysis",
      count: counts.analysisFailed,
      tab: "requests",
      filter: "attention",
    },
    {
      title: "Payments under review",
      detail: "Payments that need checking",
      count: counts.paymentReview,
      tab: "payments",
    },
    {
      title: "Flagged print jobs",
      detail: "Held or failed jobs need an operator decision",
      count: counts.flaggedJobs,
      tab: "production",
      filter: "attention",
    },
    {
      title: "Handover in progress",
      detail: "Pickup, delivery and shipment records",
      count: counts.handover,
      tab: "orders",
      filter: "handover",
    },
    {
      title: "Notification failures",
      detail: "Status emails that failed to send",
      count: counts.notificationFailures,
      tab: "notifications",
    },
  ];
  const setup = [
    {
      label: "Owner authenticator",
      ready: data.setup.ownerMfaEnabled,
      href: "/account",
      tab: null,
    },
    {
      label: "Quotation pricing policy",
      ready: data.setup.pricingPolicyActive,
      href: null,
      tab: "rates",
    },
    {
      label: "Online payments",
      ready: data.setup.onlinePaymentsEnabled,
      href: null,
      tab: "payments",
    },
    {
      label: "Order status emails",
      ready: data.notifications.enabled,
      href: null,
      tab: "notifications",
    },
  ];

  return (
    <section className={styles.overview} aria-label="Owner overview">
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.kicker}>BUSINESS OVERVIEW</p>
          <h2>A clear view of the workshop.</h2>
        </div>
        <p className={styles.timestamp}>
          Updated{" "}
          {new Date(data.generatedAt).toLocaleTimeString("en-IN", {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </p>
      </div>
      {!data.setup.ownerMfaEnabled ? (
        <div className={styles.warning}>
          Enable owner MFA before approving prices, changing production or
          managing payment exceptions.{" "}
          <Link href="/account">Set up your authenticator →</Link>
        </div>
      ) : null}
      <div className={styles.metrics}>
        <button onClick={() => selectTab("requests", "all")}>
          <span>Total requests</span>
          <strong>{totalStates(data.quoteRequests)}</strong>
          <small>All submitted and draft requests ↗</small>
        </button>
        <button onClick={() => selectTab("production", "active")}>
          <span>Active production</span>
          <strong>{counts.activeProduction}</strong>
          <small>Queued through quality checks ↗</small>
        </button>
        <button onClick={() => selectTab("orders", "all")}>
          <span>Accepted orders</span>
          <strong>{totalStates(data.orders)}</strong>
          <small>All order states ↗</small>
        </button>
        <button onClick={() => selectTab("requests", "quoted")}>
          <span>Open quotations</span>
          <strong>{data.openQuotations}</strong>
          <small>Issued and not expired ↗</small>
        </button>
      </div>
      {totalStates(data.quoteRequests) === 0 &&
      totalStates(data.orders) === 0 ? (
        <div className={styles.empty}>
          <h3>No buyer activity yet.</h3>
          <p>
            New requests will appear here. Check your pricing and account setup
            while you wait.
          </p>
        </div>
      ) : null}
      <div className={styles.columns}>
        <section className={styles.panel} aria-labelledby="owner-priorities">
          <div className={styles.panelHeading}>
            <h3 id="owner-priorities">Needs your attention</h3>
            <span>Next actions</span>
          </div>
          <div className={styles.tasks}>
            {tasks.map((task) => (
              <button
                key={task.title}
                onClick={() => selectTab(task.tab, task.filter)}
              >
                <span className={styles.count} data-active={task.count > 0}>
                  {task.count}
                </span>
                <span>
                  <strong>{task.title}</strong>
                  <small>{task.detail}</small>
                </span>
                <span aria-hidden="true">↗</span>
              </button>
            ))}
          </div>
        </section>
        <section className={styles.panel} aria-labelledby="business-setup">
          <div className={styles.panelHeading}>
            <h3 id="business-setup">Business setup</h3>
            <span>Configuration</span>
          </div>
          <ul className={styles.checklist}>
            {setup.map((item) => (
              <li key={item.label}>
                <span>
                  {item.href ? (
                    <Link href={item.href}>{item.label}</Link>
                  ) : (
                    <button onClick={() => item.tab && selectTab(item.tab)}>
                      {item.label}
                    </button>
                  )}
                </span>
                <span className={styles.badge} data-ready={item.ready}>
                  {item.ready ? "Configured" : "Not configured"}
                </span>
              </li>
            ))}
          </ul>
          <div className={styles.setupNote}>
            <strong>
              {data.setup.paymentsTestMode
                ? "Test checkout only"
                : data.setup.onlinePaymentsEnabled
                  ? "Payment gateway configured"
                  : "Online payments are not configured"}
            </strong>
            <p>
              {data.setup.paymentsTestMode
                ? "Test payments do not collect real money."
                : data.setup.onlinePaymentsEnabled
                  ? "Orders start production once payment is confirmed."
                  : "Accepted orders wait for payment until online payments are set up."}
            </p>
          </div>
        </section>
      </div>
      <div className={styles.columns}>
        <section className={styles.panel} aria-labelledby="recent-requests">
          <div className={styles.panelHeading}>
            <h3 id="recent-requests">Latest requests</h3>
            <button onClick={() => selectTab("requests", "needs_action")}>
              Review requests →
            </button>
          </div>
          {requests.length === 0 ? (
            <p className={styles.panelEmpty}>No quote requests to review.</p>
          ) : (
            <ul className={styles.records}>
              {requests.slice(0, 5).map((row) => (
                <li key={row.id}>
                  <div>
                    <strong>
                      {row.assets.map((asset) => asset.filename).join(", ") ||
                        `Request ${row.id.slice(0, 8)}`}
                    </strong>
                    <small>
                      {row.quantity} {row.quantity === 1 ? "copy" : "copies"} ·{" "}
                      {new Date(row.createdAt).toLocaleDateString("en-IN")}
                    </small>
                  </div>
                  <StatusBadge kind="request" status={row.status} />
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className={styles.panel} aria-labelledby="recent-owner-orders">
          <div className={styles.panelHeading}>
            <h3 id="recent-owner-orders">Latest orders</h3>
            <button onClick={() => selectTab("orders", "all")}>
              All orders →
            </button>
          </div>
          {orders.length === 0 ? (
            <p className={styles.panelEmpty}>
              No quotations have been accepted yet.
            </p>
          ) : (
            <div className={styles.orderRows}>
              {orders.slice(0, 5).map((order) => (
                <button key={order.id} onClick={() => void openOrder(order.id)}>
                  <span>
                    <strong>{order.publicReference}</strong>
                    <small>
                      <StatusBadge kind="order" status={order.status} />
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
        </section>
      </div>
      <p className={styles.footnote}>
        Order amounts are accepted quotation totals, not collected revenue.
      </p>
    </section>
  );
}
