"use client";

import Link from "next/link";
import { submissionId } from "@/lib/client-crypto";
import { useRouter } from "next/navigation";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  AuthApiError,
  type AuthenticatedUser,
  getCurrentUserWithRefresh,
} from "@/lib/auth-api";
import {
  MAX_MODEL_FILES_PER_QUOTE,
  MAX_MODEL_FILE_BYTES,
  type AnalysisAssetResult,
  type AnalysisRun,
  type ModelFileRejection,
  type QuoteRequest,
  type QuoteRequestList,
  QuoteApiError,
  SUPPORTED_MODEL_EXTENSIONS,
  completeModelUpload,
  computeFileSha256,
  createQuoteRequest,
  issueModelUpload,
  listQuoteRequests,
  submitQuoteRequest,
  uploadModelToStorage,
  validateModelSelection,
} from "@/lib/quote-api";

import styles from "./quote-request.module.css";
import { listPrintPresets, type PrintPreset } from "@/lib/print-specification";
import { StatusBadge } from "@/components/status-badge";
import {
  firstInvalidStep,
  validateQuoteStep,
  type QuoteDraft,
} from "@/lib/order-journey";
import { DEFAULT_MODEL_OPTIONS, type ModelOptions } from "@/lib/model-options";
import { configuredModel } from "@/lib/configured-model";
import { CustomPrintBuilder } from "./custom-print-builder";import { PrintSpecificationSummary } from "./print-specification-summary";import { joinPresentationQueue, listPresentationQueue } from "@/lib/presentation-api";
const MAX_FILE_MIB = Math.floor(MAX_MODEL_FILE_BYTES / (1024 * 1024));



type FileProgressStatus =
  | "pending"
  | "hashing"
  | "issuing"
  | "uploading"
  | "completing"
  | "quarantined"
  | "failed";

type FileProgressEntry = Readonly<{
  name: string;
  status: FileProgressStatus;
}>;


function describeRejection(rejection: ModelFileRejection): string {
  switch (rejection.reason) {
    case "unsupported_format":
      return `"${rejection.file.name}" is not a supported format (${SUPPORTED_MODEL_EXTENSIONS.join(", ")}).`;
    case "empty_file":
      return `"${rejection.file.name}" is empty and cannot be uploaded.`;
    case "file_too_large":
      return `"${rejection.file.name}" is larger than ${MAX_FILE_MIB} MiB.`;
    default:
      return `"${rejection.file.name}" could not be accepted.`;
  }
}


function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function formatInr(paise: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
  }).format(paise / 100);
}

function progressLabel(status: FileProgressStatus): string {
  switch (status) {
    case "pending":
      return "Waiting…";
    case "hashing":
      return "Checking file…";
    case "issuing":
      return "Requesting upload…";
    case "uploading":
      return "Uploading…";
    case "completing":
      return "Finishing upload…";
    case "quarantined":
      return "Uploaded; awaiting model checks";
    case "failed":
      return "Upload failed";
    default:
      return "";
  }
}

function analysisStatusSummary(status: AnalysisRun["status"]): string {
  switch (status) {
    case "queued":
      return "Queued for checks";
    case "running":
      return "Checking your models";
    case "awaiting_profile":
      return "Your models passed our checks. Pricing continues once the print profile is ready.";
    case "succeeded":
      return "Model analysis complete";
    case "failed":
      return "Model analysis needs review";
    default:
      return status;
  }
}

function formatMillimetres(micrometres: number): string {
  const millimetres = micrometres / 1000;
  return Number.isInteger(millimetres)
    ? String(millimetres)
    : millimetres.toFixed(2);
}

function formatDimensionsMm(
  dimensionsUm: readonly [number, number, number],
): string {
  const [x, y, z] = dimensionsUm;
  return `${formatMillimetres(x)} × ${formatMillimetres(y)} × ${formatMillimetres(z)} mm`;
}

function buildVolumeFitLabel(fitsBuildVolume: boolean | null): string {
  if (fitsBuildVolume === null) {
    return "not checked";
  }
  return fitsBuildVolume ? "fits" : "exceeds";
}

function analysisAssetSummary(asset: AnalysisAssetResult): string {
  const parts: string[] = [];
  if (asset.dimensionsUm !== null) {
    parts.push(formatDimensionsMm(asset.dimensionsUm));
  }
  if (asset.triangleCount !== null) {
    parts.push(`${asset.triangleCount.toLocaleString()} triangles`);
  }
  if (asset.objectCount !== null) {
    parts.push(
      `${asset.objectCount} object${asset.objectCount === 1 ? "" : "s"}`,
    );
  }
  parts.push(`Build volume: ${buildVolumeFitLabel(asset.fitsBuildVolume)}`);
  return parts.join(" · ");
}

export function QuoteRequestPanel({ presentation = false }: { presentation?: boolean } = {}) {
  const [queuedRequestIds, setQueuedRequestIds] = useState<readonly string[]>([]);
  const [queueingRequest, setQueueingRequest] = useState<string | null>(null);
  const router = useRouter();
  const [accountAttempt, setAccountAttempt] = useState(0);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const [stepError, setStepError] = useState<string | null>(null);
  const focusedHash = useRef("");
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [loadingUser, setLoadingUser] = useState(true);
  const [userError, setUserError] = useState<string | null>(null);

  const [selectedFiles, setSelectedFiles] = useState<readonly File[]>([]);
  const [quantity, setQuantity] = useState("1");
  const [fulfillmentMode, setFulfillmentMode] = useState<
    "pickup" | "local_delivery" | "shipping"
  >("pickup");
  const [buyerNotes, setBuyerNotes] = useState("");
  const [presets, setPresets] = useState<readonly PrintPreset[]>([]);
  const [presetCode, setPresetCode] = useState("");
  const [colour, setColour] = useState("");
  const [catalogueLoading, setCatalogueLoading] = useState(true);
  const [catalogueError, setCatalogueError] = useState<string | null>(null);
  const selectedPreset = presets.find((preset) => preset.code === presetCode);

  useEffect(() => {
    let active = true;
    void listPrintPresets()
      .then((items) => {
        if (!active) return;
        setPresets(items);
        const preferred = items.find(item => Number(item.settings.layerHeightMm) === 0.2 && item.settings.infillPercent === 20 && !item.settings.supports) ?? items[0];
        setPresetCode(preferred?.code ?? "");
        setColour(preferred?.colours[0] ?? "");
      })
      .catch((caught: unknown) => {
        if (active)
          setCatalogueError(
            caught instanceof Error
              ? caught.message
              : "Print options are unavailable.",
          );
      })
      .finally(() => {
        if (active) setCatalogueLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);
  const [selectionErrors, setSelectionErrors] = useState<readonly string[]>([]);
  const [progress, setProgress] = useState<readonly FileProgressEntry[]>([]);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [completedQuote, setCompletedQuote] = useState<QuoteRequest | null>(
    null,
  );

  const [recent, setRecent] = useState<QuoteRequestList | null>(null);
  const [recentLoading, setRecentLoading] = useState(false);
  const [recentError, setRecentError] = useState<string | null>(null);

  const [model, setModel] = useState<ModelOptions>(DEFAULT_MODEL_OPTIONS);
  const [preparedKey, setPreparedKey] = useState("");
  const [queuedKey, setQueuedKey] = useState("");
  const configurationKey = JSON.stringify({ files: selectedFiles.map(file => [file.name, file.size, file.lastModified]), presetCode, colour, quantity, fulfillmentMode, buyerNotes, model });
  const currentRequest = completedQuote && preparedKey === configurationKey
    ? recent?.items.find(item => item.id === completedQuote.id) ?? completedQuote : null;
  const prepared = Boolean(currentRequest && !["analysis_failed", "rejected"].includes(currentRequest.status));
  const estimating = Boolean(currentRequest && !currentRequest.latestEstimate && ["analyzing", "analysis_ready"].includes(currentRequest.status));

  const draft: QuoteDraft = {
    fileCount: selectedFiles.length,
    selectionErrors,
    preset: selectedPreset,
    colour,
    quantity,
    fulfillmentMode,
    notes: buyerNotes,
  };
  useEffect(() => {
    const hash = window.location.hash.slice(1);
    if (
      hash === focusedHash.current ||
      !recent?.items.some((item) => hash === `request-${item.id}`)
    )
      return;
    const row = document.getElementById(hash);
    if (row) {
      focusedHash.current = hash;
      row.focus();
      row.scrollIntoView({ block: "start" });
    }
  }, [recent]);

  useEffect(() => {
    let active = true;
    void getCurrentUserWithRefresh(document.cookie)
      .then((currentUser) => {
        if (active) {
          setUser(currentUser);
          setUserError(null);
          if (currentUser.role === "owner") router.replace("/operations");
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          const signedOut =
            caught instanceof AuthApiError && caught.status === 401;
          setNeedsSignIn(signedOut);
          setUserError(
            signedOut
              ? "Please sign in to request a quote."
              : "We couldn’t confirm your account right now. You have not been signed out.",
          );
        }
      })
      .finally(() => {
        if (active) {
          setLoadingUser(false);
        }
      });
    return () => {
      active = false;
    };
  }, [accountAttempt, router]);

  const refreshRecent = useCallback(async () => {
    setRecentLoading(true);
    setRecentError(null);
    try {
      const [list, queue] = await Promise.all([
        listQuoteRequests(),
        presentation ? listPresentationQueue() : Promise.resolve(null),
      ]);
      setRecent(list);
      if (queue) setQueuedRequestIds(queue.items.map(item => item.requestId));
    } catch (caught) {
      setRecentError(
        caught instanceof QuoteApiError
          ? caught.message
          : "Recent quote requests could not be loaded.",
      );
    } finally {
      setRecentLoading(false);
    }
  }, [presentation]);

  useEffect(() => {
    if (user === null || user.role !== "buyer") {
      return;
    }
    queueMicrotask(() => {
      void refreshRecent();
    });
  }, [user, refreshRecent]);

  const analysisInProgress =
    recent?.items.some(
      (item) =>
        item.status === "analyzing" ||
        (item.status === "analysis_ready" &&
          item.latestAnalysis?.status === "succeeded"),
    ) ?? false;

  useEffect(() => {
    if (!analysisInProgress || user?.role !== "buyer") return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const list = await listQuoteRequests();
        if (active) {
          setRecent(list);
          setRecentError(null);
        }
      } catch {
        if (active)
          setRecentError("Status could not be refreshed. Reload to try again.");
      }
      if (active) timer = setTimeout(() => void poll(), 5000);
    };
    timer = setTimeout(() => void poll(), 3000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [analysisInProgress, user?.role]);

  function selectFiles(files: readonly File[]) {
    setCompletedQuote(null);
    setSubmitError(null);
    setProgress([]);
    setStepError(null);

    const validation = validateModelSelection(files);
    const errors: string[] = [];
    if (validation.tooMany) {
      errors.push(
        `Select at most ${MAX_MODEL_FILES_PER_QUOTE} files. You selected ${files.length}.`,
      );
    }
    for (const rejection of validation.rejected) {
      errors.push(describeRejection(rejection));
    }

    if (errors.length > 0) {
      setSelectionErrors(errors);
      setSelectedFiles([]);
      return;
    }

    setSelectionErrors([]);
    setModel(DEFAULT_MODEL_OPTIONS);
    setSelectedFiles(files);
  }

  function handleRemoveFile(index: number) {
    setSelectedFiles((current) =>
      current.filter((_, position) => position !== index),
    );
    setSelectionErrors([]);
    setProgress([]);
    setSubmitError(null);
  }

  function updateProgress(index: number, status: FileProgressStatus) {
    setProgress((current) =>
      current.map((entry, position) =>
        position === index ? { ...entry, status } : entry,
      ),
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (prepared && currentRequest) {
      if (!presentation || queuedKey === configurationKey) {
        router.push(presentation ? "/orders" : `/orders#request-${currentRequest.id}`);
        return;
      }
      setSubmitting(true); setSubmitError(null);
      try {
        await joinPresentationQueue(currentRequest);
        setQueuedKey(configurationKey);
        setQueuedRequestIds(ids => [...new Set([...ids, currentRequest.id])]);
      } catch (caught) {
        setSubmitError(caught instanceof Error ? caught.message : "Could not submit to the waiting list.");
      } finally { setSubmitting(false); }
      return;
    }
    if (presentation && (selectedFiles.length !== 1 || quantity !== "1" || !/\.(stl|obj)$/i.test(selectedFiles[0]?.name ?? ""))) {
      setStepError("For the automated presentation, choose one STL or OBJ model and one copy.");
      return;
    }
    const invalidStep = firstInvalidStep(draft);
    if (invalidStep !== null) {
      setStepError(validateQuoteStep(invalidStep, draft));
      return;
    }
    if (
      user === null ||
      user.role !== "buyer" ||
      selectedFiles.length === 0 ||
      !selectedPreset ||
      submitting
    ) {
      return;
    }

    setSubmitting(true);
    setSubmitError(null);
    setCompletedQuote(null);
    setProgress(
      selectedFiles.map((file) => ({ name: file.name, status: "pending" })),
    );

    try {
      const uploadFiles: File[] = [];
      for (const file of selectedFiles) uploadFiles.push(await configuredModel(file, model));
      const cookieString = document.cookie;
      const quote = await createQuoteRequest(
        submissionId(),
        cookieString,
        {
          quantity: Number(quantity),
          fulfillmentMode,
          buyerNotes,
          printPresetCode: selectedPreset.code,
          colour: colour || null,
        },
      );

      for (let index = 0; index < uploadFiles.length; index += 1) {
        const file = uploadFiles[index];
        updateProgress(index, "hashing");
        const sha256 = await computeFileSha256(file);

        updateProgress(index, "issuing");
        const intent = await issueModelUpload(
          quote.id,
          {
            clientToken: submissionId(),
            filename: file.name,
            sizeBytes: file.size,
            sha256,
          },
          cookieString,
        );

        updateProgress(index, "uploading");
        await uploadModelToStorage(intent.upload, file);

        updateProgress(index, "completing");
        const asset = await completeModelUpload(
          quote.id,
          intent.asset.id,
          cookieString,
        );
        if (asset.status !== "quarantined") {
          updateProgress(index, "failed");
          throw new QuoteApiError(
            `"${file.name}" could not be quarantined for validation. Please try again.`,
            409,
          );
        }
        updateProgress(index, "quarantined");
      }

      const submitted = await submitQuoteRequest(quote.id, cookieString);
      setCompletedQuote(submitted);
      setPreparedKey(configurationKey);
      void refreshRecent();
    } catch (caught) {
      setSubmitError(
        caught instanceof QuoteApiError
          ? caught.message
          : "Your quote request could not be submitted. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (loadingUser) {
    return <p className={styles.status}>Checking your account…</p>;
  }

  if (user === null) {
    return (
      <div className={styles.result}>
        <p className={styles.error} role="alert">
          {userError ?? "Please sign in as a buyer to request a quote."}
        </p>
        {needsSignIn ? (
          <>
            <Link className={styles.submitLink} href="/sign-in">Go to sign in</Link>
            <Link href="/sign-up">New here? Create a buyer account</Link>
          </>
        ) : (
          <button type="button" onClick={() => {
            setLoadingUser(true);
            setAccountAttempt((value) => value + 1);
          }}>Try again</button>
        )}
      </div>
    );
  }

  if (user.role === "owner") {
    return (
      <p className={styles.status}>
        Opening your dashboard…
      </p>
    );
  }

  return (
    <div className={styles.panel}>
      <CustomPrintBuilder
        files={selectedFiles} onFiles={selectFiles} onRemove={handleRemoveFile}
        presets={presets} preset={selectedPreset} onPreset={setPresetCode}
        colour={colour} onColour={setColour} quantity={quantity} onQuantity={setQuantity}
        delivery={fulfillmentMode} onDelivery={setFulfillmentMode} notes={buyerNotes} onNotes={setBuyerNotes}
        model={model} onModel={setModel} pending={submitting} estimating={estimating}
        prepared={prepared} estimatePaise={currentRequest?.latestEstimate?.totalPaise ?? null}
        durationSeconds={currentRequest?.latestEstimate?.durationSeconds ?? null}
        presentation={presentation} queued={queuedKey === configurationKey}
        error={submitError ?? stepError ?? selectionErrors[0] ?? null}
        status={submitting ? progress.map(item => `${item.name}: ${progressLabel(item.status)}`).join(" · ") : prepared ? presentation ? queuedKey === configurationKey ? "Submitted to the owner waiting list." : "Your estimate is ready. Submit this model when you are ready." : "Your request is saved. The owner will confirm the final quotation." : ""}
        catalogueLoading={catalogueLoading} catalogueError={catalogueError} onSubmit={handleSubmit}
      />

      <section
        className={styles.recent}
        aria-label="Your recent quote requests"
      >
        <h2>Recent requests</h2>
        <Link href="/orders">{presentation ? "View my waiting-list submissions & prints" : "Review final quotations & orders"}</Link>
        {recentLoading && (
          <p className={styles.status}>Loading recent requests…</p>
        )}
        {recentError && (
          <p className={styles.error} role="alert">
            {recentError}
          </p>
        )}
        {recent && recent.items.length === 0 && !recentLoading && (
          <p className={styles.help}>
            You have not submitted a quote request yet.
          </p>
        )}
        {recent && recent.items.length > 0 && (
          <ul className={styles.recentList}>
            {recent.items.map((item) => (
              <li
                key={item.id}
                id={`request-${item.id}`}
                tabIndex={-1}
                className={styles.recentRow}
              >
                <div className={styles.recentHeader}>
                  <StatusBadge kind="request" status={item.status} />
                  <span className={styles.recentMeta}>
                    {item.assets.length} file
                    {item.assets.length === 1 ? "" : "s"} ·{" "}
                    {formatDate(item.createdAt)}
                  </span>
                </div>
                <p className={styles.help}>
                  {!presentation && item.status === "quoted" ? (
                    <Link href="/orders#quotations">
                      Review your final quotation in your dashboard.
                    </Link>
                  ) : item.status === "analysis_failed" ||
                    item.status === "rejected" ? (
                    "Read the review details below before preparing another request."
                  ) : (
                    presentation ? "Your measured estimate is shown below. Submit it to the waiting list from the review panel above." : "The owner will issue a final quotation after model checks and analysis."
                  )}
                </p>
                <PrintSpecificationSummary value={item.printSpecification} />
                {item.latestAnalysis && (
                  <div className={styles.analysis}>
                    <p className={styles.analysisSummary}>
                      {analysisStatusSummary(item.latestAnalysis.status)}
                    </p>
                    {item.latestAnalysis.assets.length > 0 && (
                      <ul className={styles.analysisAssetList}>
                        {item.latestAnalysis.assets.map((asset) => (
                          <li
                            key={asset.assetId}
                            className={styles.analysisAssetRow}
                          >
                            {analysisAssetSummary(asset)}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
                {item.latestEstimate && (
                  <div className={styles.analysis}>
                    <p className={styles.analysisSummary}>
                      {presentation ? "Reference printing cost: " : "Estimated total: "}
                      {formatInr(item.latestEstimate.totalPaise)}
                    </p>
                    <p className={styles.help}>
                      {presentation
                        ? `Free presentation · ${Math.ceil(item.latestEstimate.durationSeconds / 60)} min estimated print time`
                        : `${item.latestEstimate.materialName} · valid until ${formatDate(item.latestEstimate.expiresAt)} · final approval still required`}
                    </p>
                    {presentation && (queuedRequestIds.includes(item.id) ? (
                      <Link href="/orders">View in my print queue →</Link>
                    ) : item.assets.length === 1 && item.quantity === 1 &&
                      /\.(stl|obj)$/i.test(item.assets[0].filename) && (
                      <button type="button" disabled={Boolean(queueingRequest)} onClick={async () => {
                        setQueueingRequest(item.id); setSubmitError(null);
                        try {
                          await joinPresentationQueue(item);
                          setQueuedRequestIds(ids => [...new Set([...ids, item.id])]);
                          if (item.id === currentRequest?.id) setQueuedKey(configurationKey);
                        } catch (caught) {
                          setSubmitError(caught instanceof Error ? caught.message : "Could not submit this model.");
                        } finally { setQueueingRequest(null); }
                      }}>{queueingRequest === item.id ? "Submitting…" : "Submit to waiting list →"}</button>
                    ))}
                  </div>
                )}
                {item.ownerRejectionReason ? (
                  <p>Owner review: {item.ownerRejectionReason}</p>
                ) : null}
                {item.latestAnalysis?.assets.map((asset) =>
                  asset.previewUrl ? (
                    <a
                      key={asset.assetId}
                      href={asset.previewUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      View private sliced preview
                    </a>
                  ) : null,
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
