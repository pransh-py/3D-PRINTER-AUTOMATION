"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { listQuoteRequests, type QuoteRequest } from "@/lib/quote-api";
import {
  PricingApiError,
  activatePricingPolicy,
  createPricingPolicy,
  createQuoteEstimate,
  listPricingPolicies,
  type PricingPolicy,
} from "@/lib/pricing-api";

import styles from "./auth-form.module.css";

function decimalToInteger(value: string, scale: number, label: string): number {
  if (!/^\d+(?:\.\d{1,2})?$/.test(value.trim())) {
    throw new Error(
      `${label} must be a non-negative number with at most two decimal places.`,
    );
  }
  const [whole, fraction = ""] = value.trim().split(".");
  // Every caller uses two-decimal rupees or percentages: scale into integer paise/bps exactly.
  if (scale !== 100) throw new Error("Unsupported decimal scale.");
  const result = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  if (!Number.isSafeInteger(result) || result < 0) {
    throw new Error(`${label} is outside the supported range.`);
  }
  return result;
}

function inr(paise: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
  }).format(paise / 100);
}

export function OwnerPricingPanel() {
  const [policies, setPolicies] = useState<readonly PricingPolicy[]>([]);
  const [quotes, setQuotes] = useState<readonly QuoteRequest[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const activePolicy = useMemo(
    () => policies.find((policy) => policy.status === "active") ?? null,
    [policies],
  );

  async function refresh() {
    const [nextPolicies, nextQuotes] = await Promise.all([
      listPricingPolicies(),
      listQuoteRequests(100),
    ]);
    setPolicies(nextPolicies);
    setQuotes(nextQuotes.items);
  }

  useEffect(() => {
    let active = true;
    void Promise.all([listPricingPolicies(), listQuoteRequests(100)])
      .then(([nextPolicies, nextQuotes]) => {
        if (active) {
          setPolicies(nextPolicies);
          setQuotes(nextQuotes.items);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(
            caught instanceof Error
              ? caught.message
              : "Owner pricing could not be loaded.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function submitPolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    const data = new FormData(event.currentTarget);
    try {
      const created = await createPricingPolicy(
        {
          machineRatePaisePerHour: decimalToInteger(
            String(data.get("machineRate")),
            100,
            "Machine rate",
          ),
          setupFeePaise: decimalToInteger(
            String(data.get("setupFee")),
            100,
            "Setup fee",
          ),
          minimumOrderPaise: decimalToInteger(
            String(data.get("minimumOrder")),
            100,
            "Minimum order",
          ),
          contingencyBps: decimalToInteger(
            String(data.get("contingency")),
            100,
            "Contingency",
          ),
          taxBps: decimalToInteger(String(data.get("tax")), 100, "Tax"),
          estimateValidityHours: Number(data.get("validityHours")),
          materials: [
            {
              code: String(data.get("materialCode")).trim().toLowerCase(),
              displayName: String(data.get("materialName")).trim(),
              ratePaisePerGram: decimalToInteger(
                String(data.get("materialRate")),
                100,
                "Material rate",
              ),
            },
          ],
        },
        document.cookie,
      );
      setMessage(
        `Draft rate card v${created.version} created. Review it before activation.`,
      );
      await refresh();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The rate card could not be created.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function activate(policyId: string) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const activated = await activatePricingPolicy(policyId, document.cookie);
      setMessage(`Rate card v${activated.version} is now active.`);
      await refresh();
    } catch (caught) {
      const detail =
        caught instanceof PricingApiError && caught.status === 403
          ? "Activation requires recent owner MFA. Sign out and complete MFA at sign-in, then retry."
          : caught instanceof Error
            ? caught.message
            : "The rate card could not be activated.";
      setError(detail);
    } finally {
      setBusy(false);
    }
  }

  async function estimate(
    event: FormEvent<HTMLFormElement>,
    quote: QuoteRequest,
  ) {
    event.preventDefault();
    if (quote.latestAnalysis === null) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    const data = new FormData(event.currentTarget);
    try {
      await createQuoteEstimate(
        quote.id,
        {
          clientToken: crypto.randomUUID(),
          expectedQuoteVersion: quote.version,
          analysisRunId: quote.latestAnalysis.id,
          materialCode: String(data.get("materialCode")),
        },
        document.cookie,
      );
      setMessage("Immutable estimate created and shared with the buyer.");
      await refresh();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The estimate could not be created.",
      );
    } finally {
      setBusy(false);
    }
  }

  const eligibleQuotes = quotes.filter(
    (quote) =>
      quote.latestAnalysis?.status === "succeeded" &&
      quote.latestAnalysis.materialCode !== null &&
      quote.latestEstimate === null,
  );

  return (
    <section className={styles.result} aria-labelledby="pricing-heading">
      <h2 id="pricing-heading">Owner pricing</h2>
      <p className={styles.help}>
        Changes stay as a draft until you activate them.
        Enter 0 for anything that doesn’t apply.
      </p>
      {activePolicy ? (
        <p className={styles.success}>
          Active v{activePolicy.version}:{" "}
          {activePolicy.materials.map((item) => item.displayName).join(", ")}
          {" · "}minimum {inr(activePolicy.minimumOrderPaise)}
        </p>
      ) : (
        <p className={styles.status}>
          No pricing version is active. Estimates are blocked.
        </p>
      )}

      <form className={`${styles.form} ${styles.pricingForm}`} onSubmit={submitPolicy}>
        <label className={styles.field}>
          <span className={styles.label}>Material code</span>
          <input
            className={styles.input}
            name="materialCode"
            pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
            placeholder="pla"
            required
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Material name</span>
          <input
            className={styles.input}
            name="materialName"
            placeholder="PLA"
            required
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Material rate (₹ per gram)</span>
          <input
            className={styles.input}
            name="materialRate"
            inputMode="decimal"
            placeholder="0.00"
            required
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Machine rate (₹ per hour)</span>
          <input
            className={styles.input}
            name="machineRate"
            inputMode="decimal"
            placeholder="0.00"
            required
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Setup fee (₹)</span>
          <input
            className={styles.input}
            name="setupFee"
            inputMode="decimal"
            required
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Minimum order (₹)</span>
          <input
            className={styles.input}
            name="minimumOrder"
            inputMode="decimal"
            required
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Contingency (%)</span>
          <input
            className={styles.input}
            name="contingency"
            inputMode="decimal"
            required
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Tax (%)</span>
          <input
            className={styles.input}
            name="tax"
            inputMode="decimal"
            required
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Estimate validity (hours)</span>
          <input
            className={styles.input}
            name="validityHours"
            type="number"
            min="1"
            max="720"
            required
          />
        </label>
        <button
          className={styles.secondaryButton}
          type="submit"
          disabled={busy}
        >
          Create draft rate card
        </button>
      </form>

      {policies.map((policy) => (
        <div className={styles.status} key={policy.id}>
          v{policy.version} · {policy.status} · machine{" "}
          {inr(policy.machineRatePaisePerHour)}/hour · tax {policy.taxBps / 100}
          %
          {policy.status === "draft" && (
            <button
              className={styles.secondaryButton}
              type="button"
              disabled={busy}
              onClick={() => void activate(policy.id)}
            >
              Activate v{policy.version}
            </button>
          )}
        </div>
      ))}

      <h3>Estimates ready to generate</h3>
      {eligibleQuotes.length === 0 && (
        <p className={styles.help}>
          No successfully sliced quote is waiting for an estimate.
        </p>
      )}
      {eligibleQuotes.map((quote) => {
        const matchingMaterials =
          activePolicy?.materials.filter(
            (material) => material.code === quote.latestAnalysis?.materialCode,
          ) ?? [];
        return (
          <form
            className={styles.status}
            key={quote.id}
            onSubmit={(event) => void estimate(event, quote)}
          >
            <p>
              Request {quote.id.slice(0, 8)}
            </p>
            <select
              className={styles.input}
              name="materialCode"
              required
              disabled={matchingMaterials.length === 0}
            >
              {matchingMaterials.map((material) => (
                <option key={material.id} value={material.code}>
                  {material.displayName}
                </option>
              ))}
            </select>
            {matchingMaterials.length === 0 && (
              <p className={styles.help}>
                The active rate card does not offer the material used by this
                slice.
              </p>
            )}
            <button
              className={styles.secondaryButton}
              type="submit"
              disabled={busy || matchingMaterials.length === 0}
            >
              Generate estimate
            </button>
          </form>
        );
      })}
      {message && <p className={styles.success}>{message}</p>}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
