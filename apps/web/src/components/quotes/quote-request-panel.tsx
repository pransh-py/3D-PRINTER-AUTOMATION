"use client";

import Link from "next/link";
import { type ChangeEvent, type FormEvent, useCallback, useEffect, useState } from "react";

import { AuthApiError, type AuthenticatedUser, getCurrentUserWithRefresh } from "@/lib/auth-api";
import {
  MAX_MODEL_FILES_PER_QUOTE,
  MAX_MODEL_FILE_BYTES,
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
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function progressLabel(status: FileProgressStatus): string {
  switch (status) {
    case "pending":
      return "Waiting…";
    case "hashing":
      return "Computing checksum…";
    case "issuing":
      return "Requesting upload…";
    case "uploading":
      return "Uploading…";
    case "completing":
      return "Confirming upload…";
    case "quarantined":
      return "Quarantined — pending validation";
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
      return "Analyzing — pending validation";
    case "analysis_failed":
      return "Analysis failed";
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

export function QuoteRequestPanel() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [loadingUser, setLoadingUser] = useState(true);
  const [userError, setUserError] = useState<string | null>(null);

  const [selectedFiles, setSelectedFiles] = useState<readonly File[]>([]);
  const [selectionErrors, setSelectionErrors] = useState<readonly string[]>([]);
  const [progress, setProgress] = useState<readonly FileProgressEntry[]>([]);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [completedQuote, setCompletedQuote] = useState<QuoteRequest | null>(null);

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
            caught instanceof AuthApiError ? caught.message : "Your account could not be loaded.",
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
      errors.push(`Select at most ${MAX_MODEL_FILES_PER_QUOTE} files. You selected ${files.length}.`);
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
    setSelectedFiles((current) => current.filter((_, position) => position !== index));
    setSelectionErrors([]);
  }

  function updateProgress(index: number, status: FileProgressStatus) {
    setProgress((current) =>
      current.map((entry, position) => (position === index ? { ...entry, status } : entry)),
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (user === null || user.role !== "buyer" || selectedFiles.length === 0 || submitting) {
      return;
    }

    setSubmitting(true);
    setSubmitError(null);
    setCompletedQuote(null);
    setProgress(selectedFiles.map((file) => ({ name: file.name, status: "pending" })));

    try {
      const cookieString = document.cookie;
      const quote = await createQuoteRequest(crypto.randomUUID(), cookieString);

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
        const asset = await completeModelUpload(quote.id, intent.asset.id, cookieString);
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
        Owner accounts do not submit buyer quote requests. Sign in with a buyer account to upload
        models.
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
            Supported formats: STL, 3MF, OBJ, STEP, STP. Up to {MAX_MODEL_FILES_PER_QUOTE} files,{" "}
            {MAX_FILE_MIB} MiB each.
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
                <span className={styles.fileSize}>{formatBytes(file.size)}</span>
                {progress[index] ? (
                  <span className={styles.fileStatus}>{progressLabel(progress[index].status)}</span>
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
          disabled={submitting || selectedFiles.length === 0}
        >
          {submitting ? "Uploading…" : "Submit for a quote"}
        </button>
      </form>

      {completedQuote && (
        <p className={styles.success} aria-live="polite">
          Your quote request has been submitted. Every file is quarantined and pending validation
          — no price is final until our system analysis and owner review are complete.
        </p>
      )}

      <section className={styles.recent} aria-label="Your recent quote requests">
        <h2>Recent requests</h2>
        {recentLoading && <p className={styles.status}>Loading recent requests…</p>}
        {recentError && (
          <p className={styles.error} role="alert">
            {recentError}
          </p>
        )}
        {recent && recent.items.length === 0 && !recentLoading && (
          <p className={styles.help}>You have not submitted a quote request yet.</p>
        )}
        {recent && recent.items.length > 0 && (
          <ul className={styles.recentList}>
            {recent.items.map((item) => (
              <li key={item.id} className={styles.recentRow}>
                <span className={styles.recentStatus}>{quoteStatusLabel(item.status)}</span>
                <span className={styles.recentMeta}>
                  {item.assets.length} file{item.assets.length === 1 ? "" : "s"} ·{" "}
                  {formatDate(item.createdAt)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
