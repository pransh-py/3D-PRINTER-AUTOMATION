"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import {
  type ChangeEvent,
  type FormEvent,
  useCallback,
  useEffect,
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
  type QuoteRequestStatus,
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

function quoteStatusLabel(status: QuoteRequestStatus): string {
  switch (status) {
    case "draft":
      return "Draft";
    case "analyzing":
      return "Checking printability";
    case "analysis_failed":
      return "Analysis failed";
    case "analysis_ready":
      return "Model analysis ready";
    case "estimate_ready":
      return "Estimate ready for owner review";
    case "owner_review":
      return "Awaiting owner review";
    case "quoted":
      return "Quoted";
    case "rejected":
      return "Rejected";
    default:
      return status;
  }
}

function analysisStatusSummary(status: AnalysisRun["status"]): string {
  switch (status) {
    case "queued":
      return "Validation queued";
    case "running":
      return "Validating models";
    case "awaiting_profile":
      return "Models passed source validation. An approved AD5X slicer profile is still required before slicing or estimating.";
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

  useEffect(() => {
    let active = true;
    void getCurrentUserWithRefresh(document.cookie)
      .then((currentUser) => {
        if (active) {
          setUser(currentUser);
          setUserError(null);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setUserError(
            caught instanceof AuthApiError
              ? caught.message
              : "Your account could not be loaded.",
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
  }, []);

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
    setCompletedQuote(null);
    setSubmitError(null);
    setProgress([]);
    const fileList = event.target.files;
    const files = fileList === null ? [] : Array.from(fileList);
    event.target.value = "";
    if (files.length === 0) {
      return;
    }

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
        <Link className={styles.submitLink} href="/sign-in">
          Go to sign in
        </Link>
      </div>
    );
  }

  if (user.role === "owner") {
    return (
      <p className={styles.status}>
        Owner accounts do not submit buyer quote requests. Sign in with a buyer
        account to upload models.
      </p>
    );
  }

  return (
    <div className={styles.panel}>
      <form className={styles.form} onSubmit={handleSubmit}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="model-files">
            Model files
          </label>
          <input
            className={styles.fileInput}
            id="model-files"
            type="file"
            multiple
            accept={ACCEPT_ATTRIBUTE}
            onChange={handleFilesSelected}
            disabled={submitting}
          />
          <p className={styles.help}>
            STL, 3MF, OBJ, STEP or STP. Up to {MAX_MODEL_FILES_PER_QUOTE} files,{" "}
            {MAX_FILE_MIB} MiB each. All files use the print settings selected
            below.
          </p>
        </div>
        {selectedFiles[0] ? (
          <ModelPreview
            key={`${selectedFiles[0].name}-${selectedFiles[0].lastModified}`}
            file={selectedFiles[0]}
          />
        ) : null}
        <fieldset
          className={styles.printOptions}
          disabled={submitting || catalogueLoading}
        >
          <legend>Choose your print</legend>
          {catalogueLoading ? (
            <p role="status">Loading available materials and print settings…</p>
          ) : null}
          {catalogueError ? (
            <p role="alert">
              {catalogueError}{" "}
              <button type="button" onClick={() => window.location.reload()}>
                Try again
              </button>
            </p>
          ) : null}
          {!catalogueLoading && !catalogueError && presets.length === 0 ? (
            <p role="status">
              The owner is configuring print options and prices. Ordering opens
              when those are ready.
            </p>
          ) : null}
          {selectedPreset ? (
            <>
              <label htmlFor="print-material">Material</label>
              <select
                id="print-material"
                value={selectedPreset.materialCode}
                onChange={(event) => {
                  const next = presets.find(
                    (preset) => preset.materialCode === event.target.value,
                  );
                  setPresetCode(next?.code ?? "");
                  setColour(next?.colours[0] ?? "");
                }}
              >
                {Array.from(
                  new Set(presets.map((preset) => preset.materialCode)),
                ).map((code) => (
                  <option value={code} key={code}>
                    {
                      presets.find((preset) => preset.materialCode === code)
                        ?.settings.filamentType
                    }
                  </option>
                ))}
              </select>
              <label htmlFor="print-preset">Quality and infill</label>
              <select
                id="print-preset"
                value={presetCode}
                onChange={(event) => {
                  const next = presets.find(
                    (preset) => preset.code === event.target.value,
                  );
                  setPresetCode(event.target.value);
                  setColour(next?.colours[0] ?? "");
                }}
              >
                {presets
                  .filter(
                    (preset) =>
                      preset.materialCode === selectedPreset.materialCode,
                  )
                  .map((preset) => (
                    <option value={preset.code} key={preset.code}>
                      {preset.label}: {preset.settings.layerHeightMm} mm,{" "}
                      {preset.settings.infillPercent}% infill
                    </option>
                  ))}
              </select>
              {selectedPreset.colours.length ? (
                <>
                  <label htmlFor="print-colour">Filament colour</label>
                  <select
                    id="print-colour"
                    value={colour}
                    onChange={(event) => setColour(event.target.value)}
                  >
                    {selectedPreset.colours.map((option) => (
                      <option key={option}>{option}</option>
                    ))}
                  </select>
                </>
              ) : (
                <p className={styles.help}>
                  The owner will confirm the loaded filament colour before
                  printing.
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
                These settings are used together for slicing. Model dimensions
                are preserved; use millimetres for STL and OBJ. Colour is loaded
                and checked by the owner.
              </p>
            </>
          ) : null}
        </fieldset>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="model-quantity">
            Copies of each model
          </label>
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
          <label className={styles.label} htmlFor="fulfillment-mode">
            Fulfilment
          </label>
          <select
            id="fulfillment-mode"
            value={fulfillmentMode}
            disabled={submitting}
            onChange={(event) =>
              setFulfillmentMode(event.target.value as typeof fulfillmentMode)
            }
          >
            <option value="pickup">Pickup</option>
            <option value="local_delivery">Local delivery</option>
            <option value="shipping">Pan-India shipping</option>
          </select>
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
            Notes do not change the selected print settings. The owner must
            confirm any special requirement in the quotation.
          </p>
        </div>
        {selectionErrors.length > 0 && (
          <ul className={styles.errorList} role="alert">
            {selectionErrors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        )}

        {selectedFiles.length > 0 && (
          <ul className={styles.fileList} aria-live="polite">
            {selectedFiles.map((file, index) => (
              <li key={`${file.name}-${index}`} className={styles.fileRow}>
                <span className={styles.fileName}>{file.name}</span>
                <span className={styles.fileSize}>
                  {formatBytes(file.size)}
                </span>
                {progress[index] ? (
                  <span className={styles.fileStatus}>
                    {progressLabel(progress[index].status)}
                  </span>
                ) : (
                  !submitting && (
                    <button
                      className={styles.removeButton}
                      type="button"
                      onClick={() => handleRemoveFile(index)}
                    >
                      Remove
                    </button>
                  )
                )}
              </li>
            ))}
          </ul>
        )}

        {submitError && (
          <p className={styles.error} role="alert">
            {submitError}
          </p>
        )}

        <button
          className={styles.submit}
          type="submit"
          disabled={submitting || selectedFiles.length === 0 || !selectedPreset}
        >
          {submitting ? "Uploading…" : "Submit for a quote"}
        </button>
      </form>

      {completedQuote && (
        <p className={styles.success} aria-live="polite">
          Your quote request has been submitted. Every file is quarantined and
          pending validation — no price is final until our system analysis and
          owner review are complete.
        </p>
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
              <li key={item.id} className={styles.recentRow}>
                <div className={styles.recentHeader}>
                  <span className={styles.recentStatus}>
                    {quoteStatusLabel(item.status)}
                  </span>
                  <span className={styles.recentMeta}>
                    {item.assets.length} file
                    {item.assets.length === 1 ? "" : "s"} ·{" "}
                    {formatDate(item.createdAt)}
                  </span>
                </div>
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
