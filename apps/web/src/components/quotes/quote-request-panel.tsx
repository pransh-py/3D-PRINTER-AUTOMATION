"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import {
  type ChangeEvent,
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
import { PrintSpecificationSummary } from "./print-specification-summary";
import { StatusBadge } from "@/components/status-badge";
import { UiIcon } from "@/components/ui-icon";
import {
  firstInvalidStep,
  validateQuoteStep,
  type QuoteDraft,
} from "@/lib/order-journey";
import { swatchColour, type ModelStats } from "@/lib/model-options";

const STEPS = ["Model", "Print options", "Delivery", "Review"] as const;
const DELIVERY = {
  pickup: "Pickup",
  local_delivery: "Local delivery",
  shipping: "Pan-India shipping",
} as const;

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

const ACCEPT_ATTRIBUTE = SUPPORTED_MODEL_EXTENSIONS.join(",");
const MAX_FILE_MIB = Math.floor(MAX_MODEL_FILE_BYTES / (1024 * 1024));
const ModelPreview = dynamic(() => import("./model-preview"), { ssr: false });

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

function formatBytes(bytes: number): string {
  const mib = bytes / (1024 * 1024);
  if (mib >= 1) {
    return `${mib.toFixed(1)} MiB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))} KiB`;
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

export function QuoteRequestPanel() {
  const router = useRouter();
  const [accountAttempt, setAccountAttempt] = useState(0);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const [step, setStep] = useState(0);
  const [stepError, setStepError] = useState<string | null>(null);
  const [previewIndex, setPreviewIndex] = useState(0);
  const [modelStats, setModelStats] = useState<ModelStats | null>(null);
  const stepHeading = useRef<HTMLHeadingElement>(null);
  const successHeading = useRef<HTMLHeadingElement>(null);
  const movedStep = useRef(false);
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
        setPresetCode(items[0]?.code ?? "");
        setColour(items[0]?.colours[0] ?? "");
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

  const draft: QuoteDraft = {
    fileCount: selectedFiles.length,
    selectionErrors,
    preset: selectedPreset,
    colour,
    quantity,
    fulfillmentMode,
    notes: buyerNotes,
  };
  function moveStep(target: number) {
    if (submitting) return;
    if (target > step) {
      for (let current = 0; current < target; current++) {
        const error = validateQuoteStep(current, draft);
        if (error) {
          setStepError(error);
          setStep(current);
          movedStep.current = true;
          return;
        }
      }
    }
    setStepError(null);
    movedStep.current = true;
    setStep(target);
  }
  useEffect(() => {
    if (movedStep.current) stepHeading.current?.focus();
  }, [step]);
  useEffect(() => {
    if (completedQuote) successHeading.current?.focus();
  }, [completedQuote]);
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
      const list = await listQuoteRequests();
      setRecent(list);
    } catch (caught) {
      setRecentError(
        caught instanceof QuoteApiError
          ? caught.message
          : "Recent quote requests could not be loaded.",
      );
    } finally {
      setRecentLoading(false);
    }
  }, []);

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

  function handleFilesSelected(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length) selectFiles(files);
  }

  function selectFiles(files: readonly File[]) {
    setCompletedQuote(null);
    setSubmitError(null);
    setProgress([]);
    setStepError(null);
    setStep(0);
    setPreviewIndex(0);
    setModelStats(null);

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
    setSelectedFiles(files);
  }

  function handleRemoveFile(index: number) {
    setSelectedFiles((current) =>
      current.filter((_, position) => position !== index),
    );
    setSelectionErrors([]);
    setPreviewIndex(0);
    setModelStats(null);
    setProgress([]);
    setSubmitError(null);
    setStep(0);
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
    if (step !== 3) {
      moveStep(step + 1);
      return;
    }
    const invalidStep = firstInvalidStep(draft);
    if (invalidStep !== null) {
      setStepError(validateQuoteStep(invalidStep, draft));
      setStep(invalidStep);
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
      const cookieString = document.cookie;
      const quote = await createQuoteRequest(
        crypto.randomUUID(),
        cookieString,
        {
          quantity: Number(quantity),
          fulfillmentMode,
          buyerNotes,
          printPresetCode: selectedPreset.code,
          colour: colour || null,
        },
      );

      for (let index = 0; index < selectedFiles.length; index += 1) {
        const file = selectedFiles[index];
        updateProgress(index, "hashing");
        const sha256 = await computeFileSha256(file);

        updateProgress(index, "issuing");
        const intent = await issueModelUpload(
          quote.id,
          {
            clientToken: crypto.randomUUID(),
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
      setSelectedFiles([]);
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
      {completedQuote ? (
        <section className={styles.successPanel} aria-label="Request submitted">
          <UiIcon name="check" />
          <h2 ref={successHeading} tabIndex={-1}>
            Your models are in for review.
          </h2>
          <p>
            No payment has been taken. Your quotation will appear in your dashboard.
          </p>
          <ol>
            <li>We check and slice your models.</li>
            <li>
              The owner reviews the estimate and issues a final quotation.
            </li>
            <li>You review the final price, accept and continue to payment.</li>
          </ol>
          <div className={styles.wizardActions}>
            <a
              className={styles.submitLink}
              href={`#request-${completedQuote.id}`}
            >
              View status
            </a>
            <Link href="/orders">Go to your dashboard</Link>
            <button
              type="button"
              onClick={() => {
                setCompletedQuote(null);
                setStep(0);
                setProgress([]);
                setQuantity("1");
                setBuyerNotes("");
                setFulfillmentMode("pickup");
                setPreviewIndex(0);
                setModelStats(null);
                movedStep.current = true;
              }}
            >
              Start another request
            </button>
          </div>
        </section>
      ) : (
        <form className={styles.builder} onSubmit={handleSubmit} noValidate>
          <aside
            className={styles.previewColumn}
            aria-label="Your models and specification"
          >
            <div className={styles.field}>
              <label className={styles.label} htmlFor="model-files">
                Model files
              </label>
              <div
                className={styles.dropzone}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault();
                  if (!submitting && event.dataTransfer.files.length)
                    selectFiles(Array.from(event.dataTransfer.files));
                }}
              >
                <UiIcon name="upload" />
                <strong>Choose model files</strong>
                <span>or drop them here</span>
                <input
                  className={styles.fileInput}
                  id="model-files"
                  type="file"
                  multiple
                  accept={ACCEPT_ATTRIBUTE}
                  onChange={handleFilesSelected}
                  disabled={submitting}
                />
              </div>
              <p className={styles.help}>
                STL, 3MF, OBJ, STEP or STP. Up to {MAX_MODEL_FILES_PER_QUOTE}{" "}
                files, {MAX_FILE_MIB} MiB each. All files use the print settings
                selected below.
              </p>
            </div>
            {selectedFiles[previewIndex] ? (
              <ModelPreview
                key={`${selectedFiles[previewIndex].name}-${selectedFiles[previewIndex].lastModified}`}
                file={selectedFiles[previewIndex]}
                onStats={setModelStats}
                colour={swatchColour(colour)}
              />
            ) : (
              <div className={styles.previewEmpty}>
                <UiIcon name="cube" />
                <p>Your model preview appears here.</p>
                <small>
                  Preview available for STL and OBJ files.
                </small>
              </div>
            )}
            {modelStats ? (
              <p className={styles.help}>
                {modelStats.dimensionsMm
                  .map((value) => value.toFixed(1))
                  .join(" × ")}{" "}
                mm · approximate; fit is confirmed during review.
              </p>
            ) : null}
            {selectedFiles.length > 0 ? (
              <ul className={styles.fileList} aria-live="polite">
                {selectedFiles.map((file, index) => (
                  <li className={styles.fileRow} key={`${file.name}-${index}`}>
                    <span className={styles.fileName}>
                      {file.name}
                      <small>{formatBytes(file.size)}</small>
                    </span>
                    <button
                      type="button"
                      aria-label={`Preview ${file.name}`}
                      aria-pressed={previewIndex === index}
                      disabled={submitting}
                      onClick={() => {
                        setPreviewIndex(index);
                        setModelStats(null);
                      }}
                    >
                      Preview
                    </button>
                    {progress[index] ? (
                      <span className={styles.fileStatus}>
                        {progressLabel(progress[index].status)}
                      </span>
                    ) : (
                      <button
                        type="button"
                        disabled={submitting}
                        aria-label={`Remove ${file.name}`}
                        onClick={() => handleRemoveFile(index)}
                      >
                        Remove
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            ) : null}
            <div className={styles.liveSummary}>
              <p className={styles.label}>Your print specification</p>
              {selectedPreset ? (
                <PrintSpecificationSummary
                  value={{
                    presetCode: selectedPreset.code,
                    presetLabel: selectedPreset.label,
                    materialCode: selectedPreset.materialCode,
                    profileSha256: selectedPreset.profileSha256,
                    colour: colour || null,
                    settings: selectedPreset.settings,
                  }}
                />
              ) : (
                <p className={styles.help}>
                  Only configured, priced print profiles can be ordered.
                </p>
              )}
              <p className={styles.help}>
                {selectedFiles.length}{" "}
                {selectedFiles.length === 1 ? "model file" : "model files"} ·{" "}
                {quantity || "—"} {quantity === "1" ? "copy" : "copies"}{" "}
                each · {DELIVERY[fulfillmentMode]}
              </p>
            </div>
          </aside>
          <div className={styles.controls}>
            <ol className={styles.stepper} aria-label="Request steps">
              {STEPS.map((label, index) => (
                <li key={label}>
                  <button
                    type="button"
                    aria-current={step === index ? "step" : undefined}
                    disabled={submitting}
                    onClick={() => moveStep(index)}
                  >
                    <span>
                      {index < step ? <UiIcon name="check" /> : index + 1}
                    </span>
                    {label}
                  </button>
                </li>
              ))}
            </ol>
            <div className={styles.stepHeading}>
              <p className={styles.label}>
                Step {step + 1} of {STEPS.length}
              </p>
              <h2 ref={stepHeading} tabIndex={-1}>
                {
                  [
                    "Start with your model.",
                    "Make it your print.",
                    "How will you receive it?",
                    "Check everything before sending.",
                  ][step]
                }
              </h2>
            </div>
            {step === 0 ? (
              <div className={styles.modelGuide}>
                <p>
                  Add your files, then choose one print setting for all models in this request.
                </p>
                <ul>
                  <li>
                    Use millimetres for STL and OBJ. Dimensions are preserved.
                  </li>
                  <li>
                    Preview orbit changes only your view, not the printed
                    orientation.
                  </li>
                  <li>
                    We check printability and fit before issuing a final price.
                  </li>
                </ul>
              </div>
            ) : null}
            {step === 1 ? (
              <>
                <fieldset
                  className={styles.printOptions}
                  disabled={submitting || catalogueLoading}
                >
                  <legend>Choose your print</legend>
                  {catalogueLoading ? (
                    <p role="status">
                      Loading available materials and print settings…
                    </p>
                  ) : null}
                  {catalogueError ? (
                    <p role="alert">
                      {catalogueError}{" "}
                      <button
                        type="button"
                        onClick={() => window.location.reload()}
                      >
                        Try again
                      </button>
                    </p>
                  ) : null}
                  {!catalogueLoading &&
                  !catalogueError &&
                  presets.length === 0 ? (
                    <p role="status">
                      The owner is configuring print options and prices.
                      Ordering opens when those are ready.
                    </p>
                  ) : null}
                  {selectedPreset ? (
                    <>
                      <fieldset className={styles.choices}>
                        <legend>Material</legend>
                        {Array.from(
                          new Set(presets.map((preset) => preset.materialCode)),
                        ).map((code) => (
                          <label key={code} className={styles.choice}>
                            <input
                              type="radio"
                              name="material"
                              checked={selectedPreset.materialCode === code}
                              onChange={() => {
                                const next = presets.find(
                                  (preset) => preset.materialCode === code,
                                );
                                setPresetCode(next?.code ?? "");
                                setColour(next?.colours[0] ?? "");
                              }}
                            />
                            {
                              presets.find(
                                (preset) => preset.materialCode === code,
                              )?.settings.filamentType
                            }
                          </label>
                        ))}
                      </fieldset>
                      <fieldset className={styles.choices}>
                        <legend>Quality & infill</legend>
                        {presets
                          .filter(
                            (preset) =>
                              preset.materialCode ===
                              selectedPreset.materialCode,
                          )
                          .map((preset) => (
                            <label
                              className={styles.presetChoice}
                              key={preset.code}
                            >
                              <input
                                type="radio"
                                name="profile"
                                checked={presetCode === preset.code}
                                onChange={() => {
                                  setPresetCode(preset.code);
                                  setColour(preset.colours[0] ?? "");
                                }}
                              />
                              <span>
                                <strong>{preset.label}</strong>
                                <small>
                                  {preset.settings.layerHeightMm} mm layers ·{" "}
                                  {preset.settings.infillPercent}% infill ·{" "}
                                  {preset.settings.wallLoops} walls
                                  <br />
                                  {preset.settings.nozzleDiameterMm} mm nozzle ·
                                  supports{" "}
                                  {preset.settings.supports ? "on" : "off"}
                                </small>
                              </span>
                            </label>
                          ))}
                      </fieldset>
                      <p className={styles.help}>
                        Each profile sets quality, infill, walls and supports together.
                      </p>
                      {selectedPreset.colours.length ? (
                        <>
                          <fieldset className={styles.choices}>
                            <legend>Filament colour</legend>
                            {selectedPreset.colours.map((option) => (
                              <label key={option} className={styles.choice}>
                                <input
                                  type="radio"
                                  name="colour"
                                  value={option}
                                  checked={colour === option}
                                  onChange={() => setColour(option)}
                                />
                                {option}
                              </label>
                            ))}
                          </fieldset>
                        </>
                      ) : (
                        <p className={styles.help}>
                          The owner will confirm the loaded filament colour
                          before printing.
                        </p>
                      )}
                      <PrintSpecificationSummary
                        value={{
                          presetCode: selectedPreset.code,
                          presetLabel: selectedPreset.label,
                          materialCode: selectedPreset.materialCode,
                          profileSha256: selectedPreset.profileSha256,
                          colour: colour || null,
                          settings: selectedPreset.settings,
                        }}
                      />
                      <p className={styles.help}>
                        These settings are used together for slicing. Model
                        dimensions are preserved; use millimetres for STL and
                        OBJ. Colour is loaded and checked by the owner.
                      </p>
                    </>
                  ) : null}
                </fieldset>
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="model-quantity">
                    Copies of each model
                  </label>
                  <div className={styles.quantity}>
                    <button
                      type="button"
                      aria-label="One fewer copy"
                      disabled={submitting || Number(quantity) <= 1}
                      onClick={() =>
                        setQuantity(
                          String(Math.max(1, (Number(quantity) || 1) - 1)),
                        )
                      }
                    >
                      −
                    </button>
                    <input
                      id="model-quantity"
                      type="number"
                      value={quantity}
                      min={1}
                      max={100}
                      required
                      disabled={submitting}
                      onChange={(event) => setQuantity(event.target.value)}
                    />
                    <button
                      type="button"
                      aria-label="One more copy"
                      disabled={submitting || Number(quantity) >= 100}
                      onClick={() =>
                        setQuantity(
                          String(Math.min(100, (Number(quantity) || 1) + 1)),
                        )
                      }
                    >
                      +
                    </button>
                  </div>
                  <p className={styles.help}>
                    1–100 copies of every model in this request.
                  </p>
                </div>
              </>
            ) : null}
            {step === 2 ? (
              <div className={styles.field}>
                <label className={styles.label} htmlFor="fulfillment-mode">
                  Fulfilment
                </label>
                <select
                  id="fulfillment-mode"
                  value={fulfillmentMode}
                  disabled={submitting}
                  onChange={(event) =>
                    setFulfillmentMode(
                      event.target.value as typeof fulfillmentMode,
                    )
                  }
                >
                  <option value="pickup">Pickup</option>
                  <option value="local_delivery">Local delivery</option>
                  <option value="shipping">Pan-India shipping</option>
                </select>
                <p className={styles.help}>
                  Any charge appears in your quotation; the address is requested
                  when you accept.
                </p>
                <label className={styles.label} htmlFor="buyer-notes">
                  Requirements (optional)
                </label>
                <textarea
                  id="buyer-notes"
                  value={buyerNotes}
                  maxLength={1000}
                  disabled={submitting}
                  onChange={(event) => setBuyerNotes(event.target.value)}
                />
                <p className={styles.help}>
                  {buyerNotes.length}/1000 characters
                </p>
                <p className={styles.help}>
                  Notes do not change the selected print settings. The owner
                  must confirm any special requirement in the quotation.
                </p>
              </div>
            ) : null}
            {step === 3 ? (
              <div className={styles.review}>
                <section>
                  <div>
                    <h3>Models</h3>
                    <button
                      type="button"
                      disabled={submitting}
                      onClick={() => moveStep(0)}
                    >
                      Edit models
                    </button>
                  </div>
                  <ul>
                    {selectedFiles.map((file, index) => (
                      <li key={`${file.name}-${index}`}>
                        {file.name} · {formatBytes(file.size)}
                      </li>
                    ))}
                  </ul>
                </section>
                <section>
                  <div>
                    <h3>Print options</h3>
                    <button
                      type="button"
                      disabled={submitting}
                      onClick={() => moveStep(1)}
                    >
                      Edit print options
                    </button>
                  </div>
                  <p>
                    {selectedPreset?.label} ·{" "}
                    {colour || "Colour confirmed by owner"} · {quantity}{" "}
                    {quantity === "1" ? "copy" : "copies"} each
                  </p>
                  <p className={styles.help}>
                    {selectedPreset?.settings.layerHeightMm} mm layers ·{" "}
                    {selectedPreset?.settings.infillPercent}% infill · supports{" "}
                    {selectedPreset?.settings.supports ? "on" : "off"}
                  </p>
                </section>
                <section>
                  <div>
                    <h3>Delivery & requirements</h3>
                    <button
                      type="button"
                      disabled={submitting}
                      onClick={() => moveStep(2)}
                    >
                      Edit delivery
                    </button>
                  </div>
                  <p>{DELIVERY[fulfillmentMode]}</p>
                  <p className={styles.notes}>
                    {buyerNotes || "No special requirements added."}
                  </p>
                </section>
                <div className={styles.priceExplanation}>
                  <strong>A reviewed price, before you pay.</strong>
                  <p>
                    We check and slice each model, then issue a final quotation with
                    the print price, any adjustment, delivery charge and tax.
                  </p>
                  <p>
                    Submitting is free. You pay only after accepting the quotation.
                    Your files stay private.
                  </p>
                </div>
              </div>
            ) : null}
            {selectionErrors.length > 0 && (
              <ul className={styles.errorList} role="alert">
                {selectionErrors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            )}

            {stepError ? (
              <p role="alert" className={styles.error}>
                {stepError}
              </p>
            ) : null}
            {submitError && (
              <p className={styles.error} role="alert">
                {submitError} We could not confirm submission. Check recent
                requests before trying again.
              </p>
            )}

            {submitting ? (
              <p role="status">
                File{" "}
                {Math.min(
                  progress.findIndex(
                    (entry) => entry.status !== "quarantined",
                  ) + 1 || selectedFiles.length,
                  selectedFiles.length,
                )}{" "}
                of {selectedFiles.length} · uploading and checking your request…
              </p>
            ) : null}
            <div className={styles.wizardActions}>
              {step > 0 ? (
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => moveStep(step - 1)}
                >
                  Back
                </button>
              ) : null}
              <button
                className={styles.submit}
                type="submit"
                disabled={submitting}
              >
                {submitting
                  ? "Submitting…"
                  : step === 3
                    ? "Submit for review"
                    : "Continue"}
              </button>
            </div>
            <p className={styles.help}>
              No charge until you accept a final quotation and complete payment.
            </p>
          </div>
        </form>
      )}

      <section
        className={styles.recent}
        aria-label="Your recent quote requests"
      >
        <h2>Recent requests</h2>
        <Link href="/orders">Review final quotations & orders</Link>
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
                  {item.status === "quoted" ? (
                    <Link href="/orders#quotations">
                      Review your final quotation in your dashboard.
                    </Link>
                  ) : item.status === "analysis_failed" ||
                    item.status === "rejected" ? (
                    "Read the review details below before preparing another request."
                  ) : (
                    "The owner will issue a final quotation after model checks and analysis."
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
                      Estimated total:{" "}
                      {formatInr(item.latestEstimate.totalPaise)}
                    </p>
                    <p className={styles.help}>
                      {item.latestEstimate.materialName} · valid until{" "}
                      {formatDate(item.latestEstimate.expiresAt)} · final
                      approval still required
                    </p>
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
