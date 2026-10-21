"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  getCurrentUserWithRefresh,
  type AuthenticatedUser,
} from "@/lib/auth-api";
import { resolveDashboardAccess } from "@/lib/dashboard-api";
import { BuyerOverview } from "@/components/dashboard/buyer-overview";
import { OwnerOverview } from "@/components/dashboard/owner-overview";
import { SiteHeader } from "@/components/site-header";
import { StatusBadge } from "@/components/status-badge";
import {
  jobGroup,
  matchesOrder,
  matchesRequest,
  nextJob,
  orderGroup,
  orderNextAction,
  orderProgress,
  quotationState,
  requestTriage,
  statusPresentation,
  canRecoverDispatch,
} from "@/lib/order-journey";
import { listQuoteRequests, type QuoteRequest } from "@/lib/quote-api";
import { createQuoteEstimate } from "@/lib/pricing-api";
import { OwnerPricingPanel } from "@/components/auth/owner-pricing-panel";
import { PrintSpecificationSummary } from "@/components/quotes/print-specification-summary";
import { PaymentControls } from "./payment-controls";
import { PaymentPanel } from "./payment-panel";
import { NotificationPanel } from "./notification-panel";
import { OwnerModelReview } from "./owner-model-review";
import {
  acceptQuotation,
  changeFulfillment,
  changeJob,
  formatMoney,
  getArtifacts,
  getOrder,
  issueQuotation,
  listOrders,
  listProduction,
  listQuotations,
  parseRupees,
  rejectQuoteRequest,
  saveReadiness,
  type Address,
  type Order,
  type OrderDetail,
  listBridges,
  createBridgePairing,
  revokeBridge,
  authorizeHandoff,
  getStationDispatch,
  authorizeStationDispatch,
  type StationDispatch,
  WorkflowApiError,
  retrySlicing,
  type PrintJob,
  type Quotation,
} from "@/lib/workflow-api";
import styles from "./workflow.module.css";

type Run = (work: () => Promise<unknown>, notice?: string) => Promise<void>;
const statusLabel = (status: string) => status.replaceAll("_", " ");
const dateLabel = (value: string) => new Date(value).toLocaleString("en-IN");
const EVENT_LABELS: Record<string, string> = {
  prepare: "Preparation started",
  manual_started: "Manual print start recorded",
  print_completed: "Print completion recorded",
  qa_pass: "Quality check passed",
  qa_fail: "Quality check failed",
  hold: "Job placed on hold",
  release: "Returned to queue",
  print_failed: "Print failure recorded",
  plate_sent: "Preparing to print",
  plate_awaiting_start: "Printer accepted the file",
  plate_printing: "Printing",
  plate_completed: "Printer finished — quality check next",
  plate_refused: "Station declined the send — owner review",
  plate_needs_attention: "Printer attempt needs owner attention",
  plate_cancelled: "Printer confirmed cancellation",
  plate_stopped: "Printer stopped — owner review",
  plate_resolved: "Station attempt resolved locally",
};
const ORDER_FILTERS = [
  ["all", "All orders"],
  ["payment_due", "Payment due"],
  ["payment_processing", "Confirming payment"],
  ["production", "In production"],
  ["attention", "Needs attention"],
  ["handover", "Handover"],
  ["completed", "Completed"],
] as const;
const REQUEST_FILTERS = [
  ["needs_action", "Needs action"],
  ["to_quote", "Ready to quote"],
  ["attention", "Needs attention"],
  ["processing", "Processing"],
  ["quoted", "Quoted"],
  ["rejected", "Declined"],
  ["all", "All requests"],
] as const;
const TAB_LABELS: Record<string, string> = {
  overview: "Overview",
  requests: "Quote requests",
  orders: "Orders & handover",
  production: "Production",
  payments: "Payments",
  notifications: "Notifications",
  rates: "Pricing",
  bridge: "Print bridge",
  quotations: "Quotations",
};

function useClock() {
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return clock;
}

export function WorkflowPanel({ owner = false }: { owner?: boolean }) {
  const router = useRouter();
  const [access, setAccess] = useState<"resolving" | "redirecting" | "allowed" | "unavailable">(
    "resolving",
  );
  const [redirectHref, setRedirectHref] = useState<string | null>(null);
  const [tab, setTab] = useState("overview");
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);
  const [requests, setRequests] = useState<readonly QuoteRequest[]>([]);
  const [quotes, setQuotes] = useState<readonly Quotation[]>([]);
  const [orders, setOrders] = useState<readonly Order[]>([]);
  const [jobs, setJobs] = useState<readonly PrintJob[]>([]);
  const [detail, setDetail] = useState<OrderDetail | null>(null);
  const detailId = detail?.id;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [requestFilter, setRequestFilter] = useState("needs_action");
  const [requestSearch, setRequestSearch] = useState("");
  const [orderFilter, setOrderFilter] = useState("all");
  const [orderSearch, setOrderSearch] = useState("");
  const [quoteFilter, setQuoteFilter] = useState("actionable");
  const [productionFilter, setProductionFilter] = useState("active");
  const detailHost = useRef<HTMLDivElement>(null);
  const focusDetail = useRef(false);
  const clock = useClock();
  const groups = owner
    ? [
        {
          name: "Workflow",
          tabs: ["overview", "requests", "orders", "production", "payments"],
        },
        { name: "Setup", tabs: ["rates", "notifications", "bridge"] },
      ]
    : [{ name: "Your prints", tabs: ["overview", "quotations", "orders"] }];
  function selectTab(next: string, filter?: string) {
    if (!groups.some((group) => group.tabs.includes(next))) return;
    setTab(next);
    if (next === "quotations" && filter) setQuoteFilter(filter);
    if (next === "orders" && filter) {
      setOrderFilter(filter);
      setOrderSearch("");
    }
    if (next === "requests" && filter) {
      setRequestFilter(filter);
      setRequestSearch("");
    }
    if (
      next === "production" &&
      filter &&
      ["active", "attention", "all"].includes(filter)
    )
      setProductionFilter(filter);
    window.history.replaceState(null, "", `#${next}`);
  }
  useEffect(() => {
    const valid = owner
      ? [
          "overview",
          "requests",
          "orders",
          "production",
          "payments",
          "rates",
          "notifications",
          "bridge",
        ]
      : ["overview", "quotations", "orders"];
    const followHash = () => {
      const next = window.location.hash.slice(1);
      if (valid.includes(next)) setTab(next);
    };
    queueMicrotask(followHash);
    window.addEventListener("hashchange", followHash);
    return () => window.removeEventListener("hashchange", followHash);
  }, [owner]);
  useEffect(() => {
    if (detail && focusDetail.current && detailHost.current) {
      detailHost.current.focus();
      detailHost.current.scrollIntoView({ block: "start" });
      focusDetail.current = false;
    }
  }, [detail]);
  const quoteStatus = (id: string) =>
    quotes.find((quote) => quote.quoteRequestId === id)?.status;
  const requestGroup = (request: QuoteRequest) =>
    requestTriage(request, quoteStatus(request.id));
  const inRequestFilter = (request: QuoteRequest, filter: string) =>
    filter === "all" ||
    (filter === "needs_action"
      ? ["to_quote", "attention"].includes(requestGroup(request))
      : requestGroup(request) === filter);
  const filteredRequests = requests.filter(
    (request) =>
      inRequestFilter(request, requestFilter) &&
      matchesRequest(request, requestSearch),
  );
  const filteredOrders = orders.filter(
    (order) =>
      (orderFilter === "all" || orderGroup(order.status) === orderFilter) &&
      matchesOrder(order, orderSearch),
  );
  const filteredQuotes = quotes.filter((quote) =>
    quoteFilter === "closed"
      ? ["expired", "closed"].includes(quotationState(quote, clock))
      : quotationState(quote, clock) === quoteFilter,
  );
  const filteredJobs = jobs.filter(
    (job) =>
      productionFilter === "all" || jobGroup(job.status) === productionFilter,
  );
  const hasActiveWork = orders.some((order) => !["completed", "other"].includes(orderGroup(order.status)))
    || jobs.some((job) => jobGroup(job.status) === "active");
  const next = nextJob(jobs);

  function leaveWorkspace(outcome: unknown) {
    const decision = resolveDashboardAccess(owner ? "owner" : "buyer", outcome);
    if (decision.kind !== "allow") {
      setUser(null);
      setDetail(null);
      setRequests([]);
      setQuotes([]);
      setOrders([]);
      setJobs([]);
      if (decision.kind === "redirect") {
        setRedirectHref(decision.href);
        setAccess("redirecting");
        router.replace(decision.href);
      } else {
        setAccess("unavailable");
      }
      return true;
    }
    return false;
  }

  async function load() {
    let currentUser: AuthenticatedUser;
    try {
      currentUser = await getCurrentUserWithRefresh(document.cookie);
    } catch (caught) {
      leaveWorkspace(caught);
      return false;
    }
    if (leaveWorkspace(currentUser.role)) return false;
    const [quoteRows, orderRows, requestRows, jobRows] = await Promise.all([
      listQuotations(),
      listOrders(),
      owner ? listQuoteRequests(100) : null,
      owner ? listProduction() : null,
    ]);
    setQuotes(quoteRows);
    setOrders(orderRows);
    if (requestRows) setRequests(requestRows.items);
    if (jobRows) setJobs(jobRows);
    setRefreshKey((value) => value + 1);
    return true;
  }

  useEffect(() => {
    let active = true;
    void getCurrentUserWithRefresh(document.cookie)
      .then(async (user) => {
        if (!active) return;
        setUser(user);
        const decision = resolveDashboardAccess(owner ? "owner" : "buyer", user.role);
        if (decision.kind === "redirect") {
          setRedirectHref(decision.href);
          setAccess("redirecting");
          router.replace(decision.href);
          return;
        }
        const [quoteRows, orderRows, requestRows, jobRows] = await Promise.all([
          listQuotations(),
          listOrders(),
          owner ? listQuoteRequests(100) : null,
          owner ? listProduction() : null,
        ]);
        if (!active) return;
        setQuotes(quoteRows);
        setOrders(orderRows);
        if (requestRows) setRequests(requestRows.items);
        if (jobRows) setJobs(jobRows);
        setAccess("allowed");
      })
      .catch((caught: unknown) => {
        if (active) {
          const decision = resolveDashboardAccess(owner ? "owner" : "buyer", caught);
          setUser(null);
          if (decision.kind === "redirect") {
            setRedirectHref(decision.href);
            setAccess("redirecting");
            router.replace(decision.href);
          } else {
            setAccess("unavailable");
          }
        }
      });
    return () => {
      active = false;
    };
  }, [owner, attempt, router]);

  useEffect(() => {
    if (access !== "allowed" || busy || !hasActiveWork) return;
    let active = true;
    let polling = false;
    const timer = window.setInterval(async () => {
      if (document.visibilityState !== "visible" || polling) return;
      polling = true;
      try {
        const current = await getCurrentUserWithRefresh(document.cookie);
        const decision = resolveDashboardAccess(owner ? "owner" : "buyer", current.role);
        if (decision.kind === "redirect") {
          if (active) {
            setAccess("redirecting");
            setRedirectHref(decision.href);
            router.replace(decision.href);
          }
          return;
        }
        const [nextOrders, nextJobs, nextDetail] = await Promise.all([
          listOrders(),
          owner ? listProduction() : null,
          detailId ? getOrder(detailId) : null,
        ]);
        if (active) {
          setOrders(nextOrders);
          if (nextJobs) setJobs(nextJobs);
          if (nextDetail) setDetail(nextDetail);
        }
      } catch (caught) {
        const decision = resolveDashboardAccess(owner ? "owner" : "buyer", caught);
        if (active && decision.kind === "redirect") {
          setAccess("redirecting");
          setRedirectHref(decision.href);
          router.replace(decision.href);
        }
        // Network outages keep the last confirmed state; refresh reports service errors.
      } finally {
        polling = false;
      }
    }, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [access, busy, owner, detailId, hasActiveWork, router]);

  const run: Run = async (
    work,
    noticeText = "Saved. The workspace is up to date.",
  ) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await work();
      if (!(await load())) return;
      if (detail) setDetail(await getOrder(detail.id));
      setNotice(noticeText);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "This action could not be completed.",
      );
      // A stale-version error must not leave controls bound to old state.
      if (!(await load().catch(() => false))) return;
      if (detail) {
        const refreshed = await getOrder(detail.id).catch(() => null);
        setDetail(refreshed);
      }
    } finally {
      setBusy(false);
    }
  };

  async function openOrder(id: string) {
    setBusy(true);
    setError(null);
    try {
      const loaded = await getOrder(id);
      focusDetail.current = true;
      setDetail(loaded);
      setOrderFilter("all");
      setOrderSearch("");
      selectTab("orders");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not load the order.",
      );
    } finally {
      setBusy(false);
    }
  }

  // This guard controls presentation only; the API authorizes every protected request.
  if (access !== "allowed" || user?.role !== (owner ? "owner" : "buyer")) {
    return (
      <>
        <SiteHeader />
        <main id="main-content" tabIndex={-1} className={styles.workspace}>
          {access === "unavailable" ? (
            <>
              <p role="alert">We couldn’t confirm your account right now. You have not been signed out.</p>
              <button type="button" onClick={() => {
                setAccess("resolving");
                setError(null);
                setAttempt((value) => value + 1);
              }}>Try again</button>
            </>
          ) : (
            <>
              <p role="status">{access === "redirecting" ? "Opening your dashboard…" : "Checking your account…"}</p>
              {access === "redirecting" && redirectHref ? <Link href={redirectHref}>Continue</Link> : null}
            </>
          )}
        </main>
      </>
    );
  }

  const workspace = (
    <main id="main-content" tabIndex={-1} className={styles.workspace}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>
            {owner ? "Owner workspace" : "Buyer workspace"}
          </p>
          <h1>{owner ? "Owner dashboard" : "Your dashboard"}</h1>
        </div>
        <div className={styles.headerLinks}>
          {access === "allowed" && user?.role === "buyer" ? (
            <Link href="/get-a-quote">New quote request</Link>
          ) : null}
          <Link href="/account">Account & security</Link>
        </div>
      </header>
      {error ? (
        <p role="alert" className={styles.error}>
          {error}
          {error === "Recent owner MFA required" ? (
            <>
              . <Link href="/sign-in">Sign in again with MFA</Link> before
              making changes.
            </>
          ) : null}
        </p>
      ) : null}
      {notice ? (
        <p role="status" className={styles.notice}>
          {notice}
        </p>
      ) : null}
      {access === "allowed" ? (
        <>
          <nav aria-label="Workspace sections" className={styles.tabs}>
            {groups.map((group) => (
              <div key={group.name} className={styles.navGroup}>
                <span>{group.name}</span>
                <div>
                  {group.tabs.map((item) => (
                    <button
                      type="button"
                      key={item}
                      aria-current={tab === item ? "page" : undefined}
                      onClick={() => selectTab(item)}
                    >
                      {!owner && item === "orders"
                        ? "Orders"
                        : TAB_LABELS[item]}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void run(() => Promise.resolve(), "Workspace refreshed.")
              }
            >
              Refresh
            </button>
          </nav>
          {tab === "overview" ? (
            owner ? (
              <OwnerOverview
                refreshKey={refreshKey}
                requests={requests}
                orders={orders}
                selectTab={selectTab}
                openOrder={openOrder}
              />
            ) : (
              <BuyerOverview
                refreshKey={refreshKey}
                name={user?.displayName ?? ""}
                orders={orders}
                selectTab={selectTab}
                openOrder={openOrder}
              />
            )
          ) : null}
          {tab === "requests" ? (
            <section aria-label="Quote requests">
              <h2>Quote requests</h2>
              <div className={styles.filters} aria-label="Request triage">
                {REQUEST_FILTERS.map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={requestFilter === key}
                    onClick={() => setRequestFilter(key)}
                  >
                    {label}{" "}
                    <span>
                      {
                        requests.filter((request) =>
                          inRequestFilter(request, key),
                        ).length
                      }
                    </span>
                  </button>
                ))}
              </div>
              <label className={styles.search}>
                Find a model or request
                <input
                  type="search"
                  placeholder="Filename or request number"
                  value={requestSearch}
                  onChange={(event) => setRequestSearch(event.target.value)}
                />
              </label>
              <p className={styles.resultCount} aria-live="polite">
                {filteredRequests.length} matching request(s)
              </p>
              {requests.length === 0 ? (
                <p>No requests yet.</p>
              ) : (
                filteredRequests.map((request) => (
                  <RequestCard
                    key={request.id}
                    request={request}
                    finalQuoteStatus={quoteStatus(request.id)}
                    run={run}
                    busy={busy}
                  />
                ))
              )}
              {requests.length > 0 && !filteredRequests.length ? (
                <div className={styles.empty}>
                  <h3>No requests match this view.</h3>
                  <p>Try another queue or clear the filename search.</p>
                  <button
                    onClick={() => {
                      setRequestFilter("all");
                      setRequestSearch("");
                    }}
                  >
                    View all requests
                  </button>
                </div>
              ) : null}
            </section>
          ) : null}
          {tab === "quotations" ? (
            <section aria-label="Final quotations">
              <h2>Final quotations</h2>
              <div className={styles.filters} aria-label="Quotation filters">
                {[
                  ["actionable", "Action needed"],
                  ["accepted", "Accepted"],
                  ["closed", "Closed"],
                ].map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={quoteFilter === key}
                    onClick={() => setQuoteFilter(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {quotes.length === 0 ? (
                <p>
                  No final quotations yet.{" "}
                  <Link href="/get-a-quote">Upload a model</Link> to start.
                </p>
              ) : (
                filteredQuotes.map((quote) => (
                  <QuotationCard
                    key={quote.id}
                    quote={quote}
                    busy={busy}
                    run={run}
                    accepted={openOrder}
                    orderId={
                      orders.find((order) => order.acceptedQuoteId === quote.id)
                        ?.id
                    }
                  />
                ))
              )}
              {quotes.length > 0 && !filteredQuotes.length ? (
                <div className={styles.empty}>
                  <h3>
                    {quoteFilter === "actionable"
                      ? "No quotations need a decision."
                      : "No quotations in this view."}
                  </h3>
                  <p>
                    Check accepted quotations or follow your existing orders.
                  </p>
                  <button onClick={() => selectTab("orders", "all")}>
                    View your orders
                  </button>
                </div>
              ) : null}
            </section>
          ) : null}
          {tab === "production" ? (
            <section aria-label="Production queue">
              <h2>Production queue</h2>
              <p className={styles.subtle}>
                Unfinished jobs (up to 50). Open an order for its full history.
              </p>
              <button type="button" onClick={() => selectTab("orders", "all")}>
                View order history
              </button>
              <div className={styles.productionGuide}>
                Prepare → Readiness check → Send to printer → Printing → Quality check
              </div>
              <div className={styles.filters} aria-label="Production filters">
                {[
                  ["active", "Active"],
                  ["attention", "Held or failed"],
                  ["all", "All jobs"],
                ].map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={productionFilter === key}
                    onClick={() => setProductionFilter(key)}
                  >
                    {label}{" "}
                    <span>
                      {
                        jobs.filter(
                          (job) =>
                            key === "all" || jobGroup(job.status) === key,
                        ).length
                      }
                    </span>
                  </button>
                ))}
              </div>
              {jobs.length === 0 ? (
                <p>No paid jobs in the queue.</p>
              ) : (
                filteredJobs.map((job) => (
                  <div key={`${job.id}-${job.version}`}>
                    {next?.id === job.id ? (
                      <p className={styles.nextJob}>
                        {job.status === "queued" ? "Next up" : "Current printer job"}
                      </p>
                    ) : null}
                    <JobCard job={job} order={orders.find((order) => order.id === job.orderId)} nextInQueue={next?.id === job.id} busy={busy} run={run} />
                  </div>
                ))
              )}
              {jobs.length > 0 && !filteredJobs.length ? (
                <div className={styles.empty}>
                  <h3>No jobs in this view.</h3>
                  <button onClick={() => setProductionFilter("all")}>
                    View all jobs
                  </button>
                </div>
              ) : null}
            </section>
          ) : null}
          {tab === "orders" ? (
            <section aria-label="Orders">
              <h2>Orders</h2>
              <label className={styles.search}>
                Find an order
                <input
                  type="search"
                  placeholder="Order reference, e.g. PF-…"
                  disabled={busy}
                  value={orderSearch}
                  onChange={(event) => setOrderSearch(event.target.value)}
                />
              </label>
              <div className={styles.filters} aria-label="Order filters">
                {ORDER_FILTERS.map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={orderFilter === key}
                    disabled={busy}
                    onClick={() => setOrderFilter(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <p className={styles.resultCount} aria-live="polite">
                {filteredOrders.length} of {orders.length} orders
              </p>
              {orders.length === 0 ? (
                <p>No accepted orders yet.</p>
              ) : (
                <div className={styles.orderList}>
                  {filteredOrders.map((order) => (
                    <button
                      type="button"
                      key={order.id}
                      disabled={busy}
                      aria-pressed={detail?.id === order.id}
                      onClick={() => void openOrder(order.id)}
                    >
                      <strong>{order.publicReference}</strong>
                      <StatusBadge kind="order" status={order.status} />
                      <span>{formatMoney(order.amountPaise)}</span>
                    </button>
                  ))}
                </div>
              )}
              {orders.length > 0 && !filteredOrders.length ? (
                <div className={styles.empty}>
                  <h3>No matching orders.</h3>
                  <button
                    onClick={() => {
                      setOrderSearch("");
                      setOrderFilter("all");
                    }}
                  >
                    Clear filters
                  </button>
                </div>
              ) : null}
              {detail &&
              filteredOrders.some((order) => order.id === detail.id) ? (
                <div
                  ref={detailHost}
                  tabIndex={-1}
                  className={styles.detailHost}
                >
                  <OrderCard
                    key={`${detail.id}-${detail.version}`}
                    order={detail}
                    owner={owner}
                    busy={busy}
                    run={run}
                  />
                </div>
              ) : null}
            </section>
          ) : null}
          {tab === "rates" ? (
            <section>
              <h2>Approved pricing policies</h2>
              <OwnerPricingPanel />
            </section>
          ) : null}
          {tab === "bridge" ? <BridgeCard /> : null}
          {owner && tab === "notifications" ? <NotificationPanel /> : null}
          {owner && tab === "payments" ? (
            <PaymentPanel openOrder={openOrder} />
          ) : null}
        </>
      ) : null}
    </main>
  );
  return (
    <>
      <SiteHeader dashboard={owner ? "owner" : "buyer"} />
      {workspace}
    </>
  );
}

function RequestCard({
  request,
  run,
  busy,
  finalQuoteStatus,
}: {
  request: QuoteRequest;
  run: Run;
  busy: boolean;
  finalQuoteStatus?: string;
}) {
  const [adjustment, setAdjustment] = useState("0");
  const [delivery, setDelivery] = useState(
    request.fulfillmentMode === "pickup" ? "0" : "",
  );
  const [reason, setReason] = useState("");
  const [expanded, setExpanded] = useState(false);
  const clock = useClock();
  const estimate = request.latestEstimate;
  const estimateExpired = estimate
    ? Date.parse(estimate.expiresAt) <= clock
    : false;
  const analysis = request.latestAnalysis;
  const quotable =
    ["analysis_ready", "estimate_ready", "owner_review", "quoted"].includes(
      request.status,
    ) && finalQuoteStatus !== "accepted";
  async function issue(event: FormEvent) {
    event.preventDefault();
    if (!estimate) return;
    await run(() =>
      issueQuotation(request.id, {
        estimateId: estimate.id,
        expectedVersion: request.version,
        expiresAt: estimate.expiresAt,
        adjustmentPaise: parseRupees(adjustment, true),
        fulfillmentPaise: parseRupees(delivery),
        reason: reason.trim() || null,
      }),
    );
  }
  return (
    <article className={styles.card}>
      {finalQuoteStatus === "accepted" ? (
        <p>
          Quotation accepted. Continue in Orders.
        </p>
      ) : null}
      <div className={styles.cardTitle}>
        <h3>
          {request.assets.map((asset) => asset.filename).join(", ") ||
            "No models uploaded"}
        </h3>
        <StatusBadge kind="request" status={request.status} />
      </div>
      <p>
        Request {request.id.slice(0, 8)} · {dateLabel(request.createdAt)}
      </p>
      <p className={styles.subtle}>
        {request.printSpecification?.presetLabel ?? "No saved print profile"}
      </p>
      <p className={styles.subtle}>
        {request.quantity} {request.quantity === 1 ? "copy" : "copies"} of each
        model · {statusLabel(request.fulfillmentMode)}
      </p>
      <button
        type="button"
        disabled={busy}
        aria-expanded={expanded}
        aria-controls={`review-${request.id}`}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? "Close request" : "Review request"}
      </button>
      {expanded ? (
        <div id={`review-${request.id}`} className={styles.expandedRequest}>
          <h4>Model review</h4>
          {request.buyerNotes ? (
            <p>Requirements: {request.buyerNotes}</p>
          ) : null}
          <PrintSpecificationSummary value={request.printSpecification} />
          {request.assets.map((asset) => (
            <OwnerModelReview
              key={asset.id}
              requestId={request.id}
              asset={asset}
            />
          ))}
          {request.latestAnalysis?.assets.map((asset) =>
            asset.previewUrl ? (
              <p key={asset.assetId}>
                <a
                  href={asset.previewUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  View sliced preview
                </a>
              </p>
            ) : null,
          )}
          <h4>Analysis</h4>
          <p>
            Analysis:{" "}
            {analysis ? statusLabel(analysis.status) : "not submitted"}
          </p>
          {analysis?.status === "awaiting_profile" ? (
            <p>
              Waiting for an approved slicing profile. Pricing is paused until then.
            </p>
          ) : null}
          {analysis?.status === "awaiting_profile" ||
          analysis?.failureCode?.startsWith("slicer_") ? (
            <button
              disabled={busy}
              onClick={() =>
                void run(() => retrySlicing(request.id, request.version))
              }
            >
              Retry slicing
            </button>
          ) : null}
          {analysis?.status === "succeeded" ? (
            <p>
              {analysis.assets.reduce(
                (sum, asset) => sum + (asset.filamentMg ?? 0),
                0,
              ) / 1000}{" "}
              g{" · "}
              {Math.ceil(
                analysis.assets.reduce(
                  (sum, asset) => sum + (asset.durationSeconds ?? 0),
                  0,
                ) / 60,
              )}{" "}
              min
            </p>
          ) : null}
          <h4>Pricing decision</h4>
          {quotable &&
          analysis?.status === "succeeded" &&
          (!estimate || estimateExpired) ? (
            <button
              disabled={busy}
              type="button"
              onClick={() =>
                void run(() =>
                  createQuoteEstimate(
                    request.id,
                    {
                      clientToken: crypto.randomUUID(),
                      expectedQuoteVersion: request.version,
                      analysisRunId: analysis.id,
                      materialCode: analysis.materialCode ?? "",
                    },
                    document.cookie,
                  ),
                )
              }
            >
              {estimateExpired
                ? "Recalculate expired estimate"
                : "Calculate estimate"}
            </button>
          ) : null}
          {estimate && quotable ? (
            <form
              onSubmit={(event) => void issue(event)}
              className={styles.form}
            >
              <p>
                Calculated estimate:{" "}
                <strong>{formatMoney(estimate.totalPaise)}</strong>
                {" · "}expires {dateLabel(estimate.expiresAt)}
              </p>
              <label>
                Adjustment (₹; use − for a discount)
                <input
                  value={adjustment}
                  inputMode="decimal"
                  onChange={(event) => setAdjustment(event.target.value)}
                  required
                />
              </label>
              <label>
                Approved fulfilment charge (₹)
                <input
                  value={delivery}
                  inputMode="decimal"
                  onChange={(event) => setDelivery(event.target.value)}
                  required
                />
              </label>
              <label>
                Reason for adjustment / rejection
                <textarea
                  value={reason}
                  maxLength={1000}
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              <div className={styles.actions}>
                <button disabled={busy || estimateExpired} type="submit">
                  Issue final quotation
                </button>
                <button
                  disabled={busy || !reason.trim()}
                  type="button"
                  onClick={() =>
                    void run(() =>
                      rejectQuoteRequest(
                        request.id,
                        request.version,
                        reason.trim(),
                      ),
                    )
                  }
                >
                  Reject request
                </button>
              </div>
            </form>
          ) : quotable ? (
            <div className={styles.form}>
              <label>
                Rejection reason
                <textarea
                  value={reason}
                  maxLength={1000}
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              <button
                disabled={busy || !reason.trim()}
                type="button"
                onClick={() =>
                  void run(() =>
                    rejectQuoteRequest(
                      request.id,
                      request.version,
                      reason.trim(),
                    ),
                  )
                }
              >
                Reject request
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function QuotationCard({
  quote,
  run,
  busy,
  accepted,
  orderId,
}: {
  quote: Quotation;
  run: Run;
  busy: boolean;
  accepted: (id: string) => Promise<void>;
  orderId?: string;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const clock = useClock();
  const expired = Date.parse(quote.expiresAt) <= clock;
  const deliveryAddress =
    quote.fulfillmentMode !== undefined && quote.fulfillmentMode !== "pickup";
  const [address, setAddress] = useState<Address>({
    recipientName: "",
    phoneE164: "+91",
    line1: "",
    line2: "",
    locality: "",
    district: "",
    state: "",
    postalCode: "",
    countryCode: "IN",
  });
  const valid = quote.status === "issued" && !expired;
  return (
    <article className={styles.card}>
      <div className={styles.cardTitle}>
        <h3>
          Quotation {quote.id.slice(0, 8)} · v{quote.version}
        </h3>
        <StatusBadge
          kind="quotation"
          status={
            quote.status === "issued" && expired ? "expired" : quote.status
          }
        />
      </div>
      <dl className={styles.totals}>
        <div>
          <dt>Print subtotal</dt>
          <dd>{formatMoney(quote.subtotalPaise)}</dd>
        </div>
        <div>
          <dt>Owner adjustment</dt>
          <dd>{formatMoney(quote.adjustmentPaise)}</dd>
        </div>
        <div>
          <dt>Tax</dt>
          <dd>{formatMoney(quote.taxPaise)}</dd>
        </div>
        <div>
          <dt>Fulfilment</dt>
          <dd>{formatMoney(quote.fulfillmentPaise)}</dd>
        </div>
        <div>
          <dt>Total</dt>
          <dd>
            <strong>{formatMoney(quote.totalPaise)}</strong>
          </dd>
        </div>
      </dl>
      <PrintSpecificationSummary value={quote.printSpecification} />
      <p className={styles.subtle}>
        {expired && quote.status === "issued" ? "Expired" : "Valid until"}{" "}
        {dateLabel(quote.expiresAt)}
      </p>
      {quote.ownerReason ? <p>{quote.ownerReason}</p> : null}
      <p>
        {quote.quantity ?? 1} {(quote.quantity ?? 1) === 1 ? "copy" : "copies"}{" "}
        of each model · {statusLabel(quote.fulfillmentMode ?? "pickup")}
      </p>
      {valid ? (
        <>
          <p className={styles.subtle}>
            This is the owner-issued final price. Review the specification and
            delivery details, then accept to create your order. Payment happens
            next.
          </p>
          <button
            type="button"
            disabled={busy}
            aria-expanded={reviewing}
            aria-controls={`quote-review-${quote.id}`}
            onClick={() => setReviewing((value) => !value)}
          >
            {reviewing ? "Close review" : "Review & accept"}
          </button>
        </>
      ) : null}
      {quote.status === "accepted" && orderId ? (
        <button disabled={busy} onClick={() => void accepted(orderId)}>
          View order
        </button>
      ) : null}
      {valid && reviewing ? (
        <form
          id={`quote-review-${quote.id}`}
          className={styles.form}
          onSubmit={(event) => {
            event.preventDefault();
            let acceptedId: string | null = null;
            void run(async () => {
              const order = await acceptQuotation(
                quote.id,
                deliveryAddress ? address : undefined,
              );
              acceptedId = order.id;
            }, "Quotation accepted. Continue to payment below.").then(() => {
              if (acceptedId) void accepted(acceptedId);
            });
          }}
        >
          {deliveryAddress ? (
            <div className={styles.address}>
              {(
                [
                  "recipientName",
                  "phoneE164",
                  "line1",
                  "line2",
                  "locality",
                  "district",
                  "state",
                  "postalCode",
                ] as const
              ).map((field) => (
                <label key={field}>
                  {
                    {
                      recipientName: "Recipient name",
                      phoneE164: "Phone (+91…)",
                      line1: "Address line 1",
                      line2: "Address line 2 (optional)",
                      locality: "Locality",
                      district: "District",
                      state: "State",
                      postalCode: "PIN code",
                    }[field]
                  }
                  <input
                    type={field === "phoneE164" ? "tel" : "text"}
                    inputMode={field === "postalCode" ? "numeric" : undefined}
                    pattern={
                      field === "phoneE164"
                        ? "\\+91[6-9][0-9]{9}"
                        : field === "postalCode"
                          ? "[1-9][0-9]{5}"
                          : undefined
                    }
                    autoComplete={
                      {
                        recipientName: "shipping name",
                        phoneE164: "shipping tel",
                        line1: "shipping address-line1",
                        line2: "shipping address-line2",
                        locality: "shipping address-level3",
                        district: "shipping address-level2",
                        state: "shipping address-level1",
                        postalCode: "shipping postal-code",
                      }[field]
                    }
                    value={address[field]}
                    required={field !== "line2"}
                    maxLength={field === "postalCode" ? 6 : 200}
                    onChange={(event) =>
                      setAddress((previous) => ({
                        ...previous,
                        [field]: event.target.value,
                      }))
                    }
                  />
                </label>
              ))}
            </div>
          ) : null}
          <label className={styles.check}>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            I accept this final price and understand payment is still required.
          </label>
          <button type="submit" disabled={busy || !confirmed}>
            Accept and continue to payment
          </button>
        </form>
      ) : null}
    </article>
  );
}

const readinessChecks = {
  bedClear: "Build plate is clear and correctly seated",
  materialLoaded: "The approved material is loaded",
  nozzleChecked: "Nozzle and extrusion path have been checked",
  areaClear: "Printer area is clear and safe",
  artifactReviewed: "I reviewed the approved G-code and its hash",
} as const;

function JobCard({
  job,
  order,
  nextInQueue,
  run,
  busy,
}: {
  job: PrintJob;
  order?: Order;
  nextInQueue: boolean;
  run: Run;
  busy: boolean;
}) {
  const [note, setNote] = useState("");
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [station, setStation] = useState<StationDispatch | null>(null);
  const [stationError, setStationError] = useState<string | null>(null);
  const stationClock = useClock();
  useEffect(() => {
    let active = true;
    let pending = false;
    const update = async () => {
      if (pending || document.visibilityState !== "visible") return;
      pending = true;
      try {
        const result = await getStationDispatch(job.id);
        if (active) {
          setStation(result);
          setStationError(null);
        }
      } catch {
        if (active) setStationError("Station status unavailable. Refresh before sending.");
      } finally {
        pending = false;
      }
    };
    void update();
    const monitor = ["preparing", "ready_to_print", "authorized", "claimed", "printing"].includes(job.status);
    const timer = monitor ? window.setInterval(update, 5000) : null;
    return () => {
      active = false;
      if (timer !== null) window.clearInterval(timer);
    };
  }, [job.id, job.version, job.status]);
  const automated = station?.adapter === "station-zmod-v1";
  const automaticAttempt = station?.events.some((event) => event.state === "sent") ?? false;
  const grant = station?.authorization;
  const canRecover = canRecoverDispatch(job.status, grant, stationClock);
  const latest = station?.events.at(-1);
  const [artifacts, setArtifacts] = useState<
    Awaited<ReturnType<typeof getArtifacts>>
  >([]);
  const action = (name: string) =>
    void run(() => changeJob(job.id, job.version, name, note));
  return (
    <article className={styles.card}>
      <div className={styles.cardTitle}>
        <h3>
          {order ? order.publicReference : "Print job"}
          {job.attemptNumber > 1 ? ` · attempt ${job.attemptNumber}` : ""}
        </h3>
        <StatusBadge kind="job" status={job.status} />
      </div>
      {order?.printSpecification ? <PrintSpecificationSummary value={order.printSpecification} /> : null}
      {job.ownerNote ? <p>Operator note: {job.ownerNote}</p> : null}
      <div className={styles.stationPanel}>
        <div className={styles.cardTitle}>
          <h4>Printer station</h4>
          <span>{stationError ? "Unavailable" : automated && station?.online ? "Connected" : "Not connected"}</span>
        </div>
        {stationError ? <p role="status">{stationError}</p> : station ? <>
          <p>{station.bridgeName ?? "No printer station paired yet."}</p>
          {!station.eligible ? <p>{station.reason}</p> : null}
          {automated && !station.enabled ? <p>Automatic sending is turned off.</p> : null}
          {latest ? <p><strong>{latest.state === "sent" ? "Sending" : EVENT_LABELS[`plate_${latest.state}`] ?? statusLabel(latest.state)}</strong>
            {latest.refusalCode ? ` · ${statusLabel(latest.refusalCode)}` : ""}</p> : null}
          {latest?.state === "printing" && latest.progressBps !== null ? <>
            <progress aria-label="Printer progress" max={10000} value={latest.progressBps} />
            <span>{Math.floor(latest.progressBps / 100)}%</span>
          </> : null}
          {canRecover ? <button disabled={busy || !!stationError} onClick={() => void run(async () => {
            try {
              await authorizeStationDispatch(job.id, job.version);
            } catch (caught) {
              if (caught instanceof WorkflowApiError && caught.status === 409
                  && caught.message.startsWith("authorization_reset_readiness_required")) return;
              throw caught;
            }
          }, "Send cancelled before the station claimed it — confirm readiness again.")}>Return to readiness</button> : null}
          {automated && !canRecover && ["ready_to_print", "authorized"].includes(job.status) ? <button
            disabled={busy || !!stationError || !station.enabled || !station.online || !station.eligible
              || (job.status === "authorized" && !!station.authorization && Date.parse(station.authorization.expiresAt) > stationClock)}
            onClick={() => {
              if (window.confirm("Send this exact approved order once? Confirm the bed is clear, the correct spool is loaded and someone is supervising the AD5X."))
                void run(() => authorizeStationDispatch(job.id, job.version), "Authorization saved. The station will check and send this order once.");
            }}>
            {job.status === "authorized" ? "Refresh expired authorization" : "Send approved order to printer"}
          </button> : null}
          <small>Automatic sending supports one model and one copy. No automatic resend. Larger orders use manual handoff.</small>
        </> : <p>Checking station connectivity…</p>}
      </div>
      <div className={styles.form}>
        <label>
          Operator note (required for a hold or failure)
          <textarea
            value={note}
            maxLength={1000}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
        <div className={styles.actions}>
          {job.status === "queued" ? (
            <button disabled={busy || !nextInQueue} onClick={() => action("prepare")}>
              {nextInQueue ? "Prepare next job" : "Waiting for the printer"}
            </button>
          ) : null}
          {["queued", "preparing", "ready_to_print"].includes(job.status) ? (
            <button
              disabled={busy || !note.trim()}
              onClick={() => action("hold")}
            >
              Place on hold
            </button>
          ) : null}
          {job.status === "on_hold" ? (
            <button disabled={busy} onClick={() => action("release")}>
              Return to queue
            </button>
          ) : null}
          {["preparing", "ready_to_print"].includes(job.status) ? (
            <button
              disabled={busy}
              onClick={() =>
                void run(async () => setArtifacts(await getArtifacts(job.id)))
              }
            >
              Review approved artifacts
            </button>
          ) : null}
        </div>
        {artifacts.map((artifact) => (
          <div key={artifact.id} className={styles.artifact}>
            <a href={artifact.downloadUrl}>
              Download approved G-code · part {artifact.position} · quantity{" "}
              {artifact.quantity}
            </a>
            <code>SHA-256 {artifact.sha256}</code>
          </div>
        ))}
        {job.status === "preparing" ? (
          <fieldset disabled={busy}>
            <legend>Physical readiness — expires after 10 minutes</legend>
            {Object.entries(readinessChecks).map(([key, label]) => (
              <label className={styles.check} key={key}>
                <input
                  type="checkbox"
                  checked={checks[key] ?? false}
                  onChange={(event) =>
                    setChecks((previous) => ({
                      ...previous,
                      [key]: event.target.checked,
                    }))
                  }
                />
                {label}
              </label>
            ))}
            <button
              disabled={
                !Object.keys(readinessChecks).every((key) => checks[key])
              }
              onClick={() =>
                void run(() => saveReadiness(job.id, job.version, checks))
              }
            >
              Confirm readiness
            </button>
          </fieldset>
        ) : null}
        {job.status === "ready_to_print" && station && !stationError ? (
          <button
            disabled={busy}
            onClick={() => {
              if (
                window.confirm(
                  "Only confirm after you manually started this exact approved job on the printer. No printer command is sent by this button.",
                )
              )
                action("manual_started");
            }}
          >
            Record manual print start
          </button>
        ) : null}
        {job.status === "ready_to_print" && station?.adapter === "manual-orca" ? (
          <button
            disabled={busy}
            onClick={() =>
              void run(() => authorizeHandoff(job.id, job.version))
            }
          >
            Allow paired Windows bridge to download for 2 minutes
          </button>
        ) : null}
        {["printing", "claimed"].includes(job.status) ? (
          <div className={styles.actions}>
            {job.status === "printing" && station && !stationError && !automaticAttempt ?
            <button disabled={busy} onClick={() => action("print_completed")}>
              Print finished — send to QA
            </button> : null}
            <button
              disabled={busy || !note.trim()}
              onClick={() => action("print_failed")}
            >
              Record print failure
            </button>
            <small>Recording a failure does not stop the printer. Inspect and stop it locally before clearing the bed.</small>
          </div>
        ) : null}
        {job.status === "qa" ? (
          <div className={styles.actions}>
            <button disabled={busy} onClick={() => action("qa_pass")}>
              QA passed
            </button>
            <button
              disabled={busy || !note.trim()}
              onClick={() => action("qa_fail")}
            >
              QA failed
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
}

function BridgeCard() {
  const [rows, setRows] = useState<Awaited<ReturnType<typeof listBridges>>>([]);
  const [name, setName] = useState("Windows print station");
  const [pairing, setPairing] = useState<Awaited<
    ReturnType<typeof createBridgePairing>
  > | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    void listBridges()
      .then((value) => {
        if (active) setRows(value);
      })
      .catch((caught: unknown) => {
        if (active)
          setError(
            caught instanceof Error
              ? caught.message
              : "Could not load the bridge.",
          );
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    if (!pairing) return;
    const timer = window.setTimeout(
      () => setPairing(null),
      Math.max(0, Date.parse(pairing.expiresAt) - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [pairing]);
  async function operate(work: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await work();
      setRows(await listBridges());
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Bridge action failed.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <h2>Local printer connection</h2>
      <p>
        Pair your local AD5X station so approved orders can be sent to it.
        A connected station isn’t necessarily ready to print.
      </p>
      <p>
        Run{" "}
        <code>
          python tools/run_commerce_station.py pair --api YOUR_API_ORIGIN
        </code>{" "}
        on the print station in WSL. Enter the one-use token below when prompted.
      </p>
      {error ? (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      ) : null}
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          void operate(async () => setPairing(await createBridgePairing(name)));
        }}
      >
        <label>
          Installation name
          <input
            value={name}
            required
            maxLength={100}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <button type="submit" disabled={busy}>
          Create / replace pairing token
        </button>
      </form>
      {pairing ? (
        <div className={styles.card}>
          <p>One-use token · expires {dateLabel(pairing.expiresAt)}</p>
          <code className={styles.secret}>{pairing.pairingToken}</code>
          <p>
            Do not share or photograph this token. Replacing a pairing
            invalidates the previous credential.
          </p>
          <button onClick={() => setPairing(null)}>Hide token</button>
        </div>
      ) : null}
      {rows.map((row) => (
        <article className={styles.card} key={row.id}>
          <h3>{row.name}</h3>
          <p>
            {statusLabel(row.status)} · last heartbeat:{" "}
            {row.lastHeartbeatAt
              ? dateLabel(row.lastHeartbeatAt)
              : "not connected"}
          </p>
          <button
            disabled={busy || row.status === "revoked"}
            onClick={() => {
              if (
                window.confirm(
                  "Revoke this bridge credential and all outstanding handoffs?",
                )
              )
                void operate(() => revokeBridge(row.id));
            }}
          >
            Revoke bridge
          </button>
        </article>
      ))}
    </section>
  );
}

function OrderCard({
  order,
  owner,
  run,
  busy,
}: {
  order: OrderDetail;
  owner: boolean;
  run: Run;
  busy: boolean;
}) {
  const [carrier, setCarrier] = useState("");
  const [tracking, setTracking] = useState("");
  const fulfillment = order.fulfillment;
  const progress = orderProgress(order.status, fulfillment?.mode);
  const nextAction = orderNextAction(order, owner ? "owner" : "buyer");
  const printObservation = order.timeline.findLast((event) => event.event === "plate_printing");
  const printProgress = printObservation?.progressBps;
  const nextStatus =
    fulfillment?.status === "pending"
      ? {
          pickup: "ready_for_pickup",
          local_delivery: "out_for_delivery",
          shipping: "shipped",
        }[fulfillment.mode]
      : ["ready_for_pickup", "out_for_delivery", "shipped"].includes(
            fulfillment?.status ?? "",
          )
        ? "completed"
        : null;
  return (
    <article className={styles.card}>
      <div className={styles.cardTitle}>
        <h3>{order.publicReference}</h3>
        <StatusBadge kind="order" status={order.status} />
      </div>
      <p>
        Accepted {dateLabel(order.acceptedAt)} ·{" "}
        <strong>{formatMoney(order.amountPaise)}</strong>
      </p>
      <ol className={styles.orderProgress} aria-label="Order progress">
        {progress.steps.map((label, index) => (
          <li
            key={label}
            aria-current={progress.current === index ? "step" : undefined}
            data-complete={
              progress.current !== null &&
              (index < progress.current || order.status === "completed")
            }
            data-flagged={progress.flagged && progress.current === index}
          >
            <span aria-hidden="true">
              {progress.current !== null &&
              (index < progress.current || order.status === "completed")
                ? "✓"
                : index + 1}
            </span>
            <strong>{label}</strong>
            <small>
              {progress.current === index
                ? order.status === "completed"
                  ? "Recorded"
                  : progress.flagged
                    ? "Needs attention"
                    : "Current stage"
                : progress.current !== null && index < progress.current
                  ? "Recorded"
                  : ""}
            </small>
          </li>
        ))}
      </ol>
      <section className={styles.nextAction} aria-label="Next order action">
        <p className={styles.eyebrow}>WHAT HAPPENS NEXT</p>
        <h4>{nextAction.title}</h4>
        <p>{nextAction.message}</p>
        {[
          "payment_pending",
          "payment_processing",
          "payment_failed",
          "payment_review",
        ].includes(order.status) ? (
          <PaymentControls order={order} owner={owner} busy={busy} run={run} />
        ) : null}
      </section>
      {order.status === "printing" && printObservation && printProgress != null ? (
        <div className={styles.stationPanel}>
          <strong>Your part is printing · {Math.floor(printProgress / 100)}%</strong>
          <progress aria-label="Your print progress" value={printProgress} max={10000} />
          <small>Updated {dateLabel(printObservation.at)}.</small>
        </div>
      ) : null}
      <PrintSpecificationSummary value={order.printSpecification} />
      {order.payment.testMode ? (
        <p className={styles.boundary}>
          Test order. Not a real payment or confirmed print.
        </p>
      ) : null}
      <dl className={styles.totals}>
        {order.lines.map((line, index) => (
          <div key={`${line.kind}-${index}`}>
            <dt>{line.description}</dt>
            <dd>{formatMoney(line.amountPaise)}</dd>
          </div>
        ))}
      </dl>
      {fulfillment ? (
        <>
          <h4>Fulfilment · {statusLabel(fulfillment.mode)}</h4>
          {fulfillment.destination ? (
            <address>
              {fulfillment.destination.recipientName}
              <br />
              {fulfillment.destination.phoneE164}
              <br />
              {fulfillment.destination.line1}
              <br />
              {fulfillment.destination.line2 ? (
                <>
                  {fulfillment.destination.line2}
                  <br />
                </>
              ) : null}
              {fulfillment.destination.locality},{" "}
              {fulfillment.destination.district}
              <br />
              {fulfillment.destination.state}{" "}
              {fulfillment.destination.postalCode}, India
            </address>
          ) : null}
          <p>
            {statusPresentation("fulfillment", fulfillment.status).label}
            {fulfillment.carrierName ? ` · ${fulfillment.carrierName}` : ""}
            {fulfillment.trackingReference
              ? ` · Tracking: ${fulfillment.trackingReference}`
              : ""}
          </p>
        </>
      ) : null}
      {owner &&
      fulfillment &&
      nextStatus &&
      ["qa", "ready_for_pickup", "out_for_delivery", "shipped"].includes(
        order.status,
      ) ? (
        <form
          className={styles.form}
          onSubmit={(event) => {
            event.preventDefault();
            if (
              window.confirm(
                nextStatus === "completed"
                  ? "Confirm the buyer has collected or received this order?"
                  : "Confirm QA passed and this order is ready for fulfilment?",
              )
            )
              void run(() =>
                changeFulfillment(
                  order.id,
                  order.version,
                  nextStatus,
                  carrier,
                  tracking,
                ),
              );
          }}
        >
          {fulfillment.mode === "shipping" &&
          fulfillment.status === "pending" ? (
            <>
              <label>
                Carrier
                <input
                  value={carrier}
                  required
                  maxLength={100}
                  onChange={(event) => setCarrier(event.target.value)}
                />
              </label>
              <label>
                Tracking reference
                <input
                  value={tracking}
                  required
                  maxLength={100}
                  onChange={(event) => setTracking(event.target.value)}
                />
              </label>
            </>
          ) : null}
          <button disabled={busy} type="submit">
            Record {statusLabel(nextStatus)}
          </button>
        </form>
      ) : null}
      <h4>History</h4>
      {order.timeline.length === 0 ? (
        <p>Production has not started.</p>
      ) : (
        <ol className={styles.timeline}>
          {order.timeline.map((event, index) => (
            <li key={`${event.at}-${index}`}>
              {EVENT_LABELS[event.event] ?? statusLabel(event.event)}
              {event.event === "plate_printing" && event.progressBps !== null ? ` · ${Math.floor(event.progressBps / 100)}%` : ""}
              <time>{dateLabel(event.at)}</time>
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}
