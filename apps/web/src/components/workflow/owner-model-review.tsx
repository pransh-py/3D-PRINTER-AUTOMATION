"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import type { ModelAsset } from "@/lib/quote-api";
import styles from "./workflow.module.css";

const ModelPreview = dynamic(() => import("../quotes/model-preview"), {
  ssr: false,
});
const MAX_PREVIEW_BYTES = 16 * 1024 * 1024;

export function OwnerModelReview({
  requestId,
  asset,
}: {
  requestId: string;
  asset: ModelAsset;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  if (asset.status !== "validated") return null;
  const url = `/api/v1/owner/quote-requests/${requestId}/models/${asset.id}`;
  const previewable =
    ["stl", "obj"].includes(asset.format) &&
    asset.expectedSizeBytes <= MAX_PREVIEW_BYTES;

  async function inspect() {
    const request = new AbortController();
    controller.current?.abort();
    controller.current = request;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(url, {
        cache: "no-store",
        credentials: "same-origin",
        signal: request.signal,
      });
      if (!response.ok || !response.body)
        throw new Error(
          "The private model could not be loaded. Sign in again or retry.",
        );
      const reader = response.body.getReader();
      const chunks: Uint8Array<ArrayBuffer>[] = [];
      let size = 0;
      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > MAX_PREVIEW_BYTES)
            throw new Error(
              "This model is too large for the browser preview. Use the private download.",
            );
          chunks.push(new Uint8Array(value));
        }
      } finally {
        await reader.cancel();
      }
      if (!request.signal.aborted)
        setFile(new File(chunks, `model.${asset.format}`));
    } catch (caught) {
      if (!request.signal.aborted)
        setError(
          caught instanceof Error
            ? caught.message
            : "The model could not be loaded.",
        );
    } finally {
      if (!request.signal.aborted) setLoading(false);
    }
  }

  return (
    <section aria-label={`Review ${asset.filename}`}>
      <div className={styles.actions}>
        <a href={url}>Download {asset.filename}</a>
        {previewable && !file ? (
          <button
            type="button"
            disabled={loading}
            onClick={() => void inspect()}
          >
            {loading
              ? "Loading model…"
              : `Preview ${asset.filename}`}
          </button>
        ) : null}
        {file ? (
          <button type="button" onClick={() => setFile(null)}>
            Close model preview
          </button>
        ) : null}
      </div>
      {error ? <p role="alert">{error}</p> : null}
      {file ? <ModelPreview file={file} /> : null}
    </section>
  );
}
