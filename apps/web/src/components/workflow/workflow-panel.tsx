"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { getCurrentUserWithRefresh } from "@/lib/auth-api";
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
  retrySlicing,
  type PrintJob,
  type Quotation,
} from "@/lib/workflow-api";
import styles from "./workflow.module.css";

type Run = (work: () => Promise<unknown>) => Promise<void>;
const statusLabel = (status: string) => status.replaceAll("_", " ");
const dateLabel = (value: string) => new Date(value).toLocaleString("en-IN");

function useClock() {
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return clock;
}

export function WorkflowPanel({ owner = false }: { owner?: boolean }) {
  const [access, setAccess] = useState<"loading" | "allowed" | "denied">(
    "loading",
  );
  const [tab, setTab] = useState(owner ? "requests" : "quotations");
  const [requests, setRequests] = useState<readonly QuoteRequest[]>([]);
  const [quotes, setQuotes] = useState<readonly Quotation[]>([]);
  const [orders, setOrders] = useState<readonly Order[]>([]);
  const [jobs, setJobs] = useState<readonly PrintJob[]>([]);
  const [detail, setDetail] = useState<OrderDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
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
  }

  useEffect(() => {
    let active = true;
    void getCurrentUserWithRefresh(document.cookie)
      .then(async (user) => {
        if (owner && user.role !== "owner")
          throw new Error("This workspace is for the owner only.");
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
          setError(
            caught instanceof Error
              ? caught.message
              : "Could not load this workspace.",
          );
          setAccess("denied");
        }
      });
    return () => {
      active = false;
    };
  }, [owner]);

  const run: Run = async (work) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await work();
      await load();
      if (detail) setDetail(await getOrder(detail.id));
      setNotice("Saved. The workspace is up to date.");
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "This action could not be completed.",
      );
      // A stale-version error must not leave controls bound to old state.
      await load().catch(() => undefined);
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
      setDetail(await getOrder(id));
      setTab("orders");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not load the order.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={styles.workspace}>
      <div className={styles.workspaceNav}>
        <Link href="/" className={styles.brand}>
          PrintFlow <span>3D</span>
        </Link>
        <Link href="/get-a-quote">New quote request</Link>
      </div>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>
            {owner ? "Owner workspace" : "Your printing requests"}
          </p>
          <h1>{owner ? "Operations" : "Quotations & orders"}</h1>
          <p>
            {owner
              ? "Review prices, prepare one job at a time, and record fulfilment."
              : "Review the owner’s final quotation and follow your order."}
          </p>
        </div>
        <Link href="/account">Account & security</Link>
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
      {access === "loading" ? (
        <p role="status">Loading protected records…</p>
      ) : null}
      {access === "denied" ? (
        <Link href="/sign-in">Sign in to continue</Link>
      ) : null}
      {access === "allowed" ? (
        <>
          <nav aria-label="Workspace sections" className={styles.tabs}>
            {(owner
              ? [
                  "requests",
                  "production",
                  "orders",
                  "payments",
                  "notifications",
                  "rates",
                  "bridge",
                ]
              : ["quotations", "orders"]
            ).map((item) => (
              <button
                type="button"
                key={item}
                aria-current={tab === item ? "page" : undefined}
                onClick={() => setTab(item)}
              >
                {statusLabel(item)}
              </button>
            ))}
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(load)}
            >
              Refresh
            </button>
          </nav>
          <div className={styles.boundary}>
            Only server-confirmed payment can release an order into production.{" "}
            {owner
              ? "Printer actions below are operator records, not commands sent to an AD5X."
              : "Your order status is recorded by the owner; automatic printer dispatch is disabled."}
          </div>
          {tab === "requests" ? (
            <section aria-label="Quote requests">
              <h2>Quote requests</h2>
              {requests.length === 0 ? (
                <p>No requests yet.</p>
              ) : (
                requests.map((request) => (
                  <RequestCard
                    key={request.id}
                    request={request}
                    finalQuoteStatus={
                      quotes.find(
                        (quote) => quote.quoteRequestId === request.id,
                      )?.status
                    }
                    run={run}
                    busy={busy}
                  />
                ))
              )}
            </section>
          ) : null}
          {tab === "quotations" ? (
            <section aria-label="Final quotations">
              <h2>Final quotations</h2>
              <p>
                An estimate is not a final quotation. Only owner-issued
                quotations can be accepted.
              </p>
              {quotes.length === 0 ? (
                <p>
                  No final quotations yet.{" "}
                  <Link href="/get-a-quote">Upload a model</Link> to start.
                </p>
              ) : (
                quotes.map((quote) => (
                  <QuotationCard
                    key={quote.id}
                    quote={quote}
                    busy={busy}
                    run={run}
                    accepted={(id) => void openOrder(id)}
                  />
                ))
              )}
            </section>
          ) : null}
          {tab === "production" ? (
            <section aria-label="Production queue">
              <h2>Production queue</h2>
              <p>Only confirmed, captured payment evidence creates a job.</p>
              {jobs.length === 0 ? (
                <p>No paid jobs in the queue.</p>
              ) : (
                jobs.map((job) => (
                  <JobCard
                    key={`${job.id}-${job.version}`}
                    job={job}
                    busy={busy}
                    run={run}
                  />
                ))
              )}
            </section>
          ) : null}
          {tab === "orders" ? (
            <section aria-label="Orders">
              <h2>Orders</h2>
              {orders.length === 0 ? (
                <p>No accepted orders yet.</p>
              ) : (
                <div className={styles.orderList}>
                  {orders.map((order) => (
                    <button
                      type="button"
                      key={order.id}
                      disabled={busy}
                      onClick={() => void openOrder(order.id)}
                    >
                      <strong>{order.publicReference}</strong>
                      <span>{statusLabel(order.status)}</span>
                      <span>{formatMoney(order.amountPaise)}</span>
                    </button>
                  ))}
                </div>
              )}
              {detail ? (
                <OrderCard
                  key={`${detail.id}-${detail.version}`}
                  order={detail}
                  owner={owner}
                  busy={busy}
                  run={run}
                />
              ) : null}
            </section>
          ) : null}
          {tab === "rates" ? (
            <section>
              <h2>Approved pricing policies</h2>
              <p>
                No business rates or tax treatment are assumed. Activate only an
                owner-approved policy.
              </p>
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
          Final quotation accepted. Its price is locked; continue in Orders.
        </p>
      ) : null}
      <div className={styles.cardTitle}>
        <h3>Request {request.id.slice(0, 8)}</h3>
        <span className={styles.status}>{statusLabel(request.status)}</span>
      </div>
      <p>
        {request.assets.map((asset) => asset.filename).join(", ") ||
          "No models uploaded"}
      </p>
      <p>
        {request.quantity} copies of each model ·{" "}
        {statusLabel(request.fulfillmentMode)}
      </p>
      {request.buyerNotes ? <p>Requirements: {request.buyerNotes}</p> : null}
      <PrintSpecificationSummary value={request.printSpecification} />
      {request.assets.map((asset) => (
        <OwnerModelReview key={asset.id} requestId={request.id} asset={asset} />
      ))}
      {request.latestAnalysis?.assets.map((asset) =>
        asset.previewUrl ? (
          <p key={asset.assetId}>
            <a
              href={asset.previewUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              View private sliced preview
            </a>
          </p>
        ) : null,
      )}
      <p>
        Analysis: {analysis ? statusLabel(analysis.status) : "not submitted"}
      </p>
      {analysis?.status === "awaiting_profile" ? (
        <p>
          Waiting for an approved AD5X slicing profile. No price can be issued
          yet.
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
          Retry after configuring approved slicing profiles
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
            ? "Refresh expired estimate from approved rates"
            : "Calculate estimate from approved rates"}
        </button>
      ) : null}
      {estimate && quotable ? (
        <form onSubmit={(event) => void issue(event)} className={styles.form}>
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
                rejectQuoteRequest(request.id, request.version, reason.trim()),
              )
            }
          >
            Reject request
          </button>
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
}: {
  quote: Quotation;
  run: Run;
  busy: boolean;
  accepted: (id: string) => void;
}) {
  const [confirmed, setConfirmed] = useState(false);
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
        <span className={styles.status}>{statusLabel(quote.status)}</span>
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
      <p>Valid until {dateLabel(quote.expiresAt)}</p>
      {quote.ownerReason ? <p>{quote.ownerReason}</p> : null}
      <p>
        {quote.quantity ?? 1} copies of each model ·{" "}
        {statusLabel(quote.fulfillmentMode ?? "pickup")}
      </p>
      {valid ? (
        <form
          className={styles.form}
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              const order = await acceptQuotation(
                quote.id,
                deliveryAddress ? address : undefined,
              );
              accepted(order.id);
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
            Accept quotation
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
  run,
  busy,
}: {
  job: PrintJob;
  run: Run;
  busy: boolean;
}) {
  const [note, setNote] = useState("");
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [artifacts, setArtifacts] = useState<
    Awaited<ReturnType<typeof getArtifacts>>
  >([]);
  const action = (name: string) =>
    void run(() => changeJob(job.id, job.version, name, note));
  return (
    <article className={styles.card}>
      <div className={styles.cardTitle}>
        <h3>
          Job {job.id.slice(0, 8)} · attempt {job.attemptNumber}
        </h3>
        <span className={styles.status}>{statusLabel(job.status)}</span>
      </div>
      {job.ownerNote ? <p>Operator note: {job.ownerNote}</p> : null}
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
            <button disabled={busy} onClick={() => action("prepare")}>
              Prepare next job
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
        {job.status === "ready_to_print" ? (
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
        {job.status === "ready_to_print" ? (
          <button
            disabled={busy}
            onClick={() =>
              void run(() => authorizeHandoff(job.id, job.version))
            }
          >
            Allow paired Windows bridge to download for 2 minutes
          </button>
        ) : null}
        {job.status === "printing" ? (
          <div className={styles.actions}>
            <button disabled={busy} onClick={() => action("print_completed")}>
              Print finished — send to QA
            </button>
            <button
              disabled={busy || !note.trim()}
              onClick={() => action("print_failed")}
            >
              Record print failure
            </button>
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
      <h2>Windows handoff bridge</h2>
      <p>
        This outbound-only adapter downloads verified G-code. Automatic printer
        dispatch is disabled. No printer state is inferred from a bridge
        heartbeat.
      </p>
      <p>
        Run{" "}
        <code>
          python services/bridge/bridge.py --api YOUR_API_ORIGIN --pair
        </code>{" "}
        on the print station. Enter the one-use token below when prompted. Store
        the returned credential securely on Windows.
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
        <span className={styles.status}>{statusLabel(order.status)}</span>
      </div>
      <p>
        Accepted {dateLabel(order.acceptedAt)} ·{" "}
        <strong>{formatMoney(order.amountPaise)}</strong>
      </p>
      <PrintSpecificationSummary value={order.printSpecification} />
      {order.payment.testMode ? (
        <p className={styles.boundary}>
          Test environment. This order is not evidence of a real payment or
          physical print.
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
      {[
        "payment_pending",
        "payment_processing",
        "payment_failed",
        "payment_review",
      ].includes(order.status) ? (
        <PaymentControls order={order} owner={owner} busy={busy} run={run} />
      ) : null}
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
            {statusLabel(fulfillment.status)}
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
      <h4>Production history</h4>
      {order.timeline.length === 0 ? (
        <p>Production has not started.</p>
      ) : (
        <ol className={styles.timeline}>
          {order.timeline.map((event, index) => (
            <li key={`${event.at}-${index}`}>
              {statusLabel(event.event)}
              <time>{dateLabel(event.at)}</time>
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}
