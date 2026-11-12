import React, { useState } from "react";
import client, { errorMessage } from "../api/client";

/** Progress / partial-failure / retry panel for the AI extraction job. */
export default function JobStatus({ store, setStore, compact = false }) {
  const job = store.job;
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState("");
  if (!job) return null;

  async function retry() {
    setRetrying(true);
    setError("");
    try {
      const { data } = await client.post(`/qr/stores/${store.id}/analysis/retry`);
      setStore((s) => ({ ...s, job: data }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRetrying(false);
    }
  }

  const running = ["queued", "running"].includes(job.status);
  const pct = job.progress.total ? Math.round((job.progress.done / job.progress.total) * 100) : 0;

  if (running) {
    return (
      <div className="qr-job qr-job-running" role="status" aria-live="polite">
        <span className="qr-spinner" aria-hidden="true" />
        <div>
          <strong>Reading your {job.progress.total > 1 ? "pages" : "photo"}…</strong>
          <p className="muted small">
            {job.progress.done} of {job.progress.total} done. This usually takes under a minute per page — you can keep
            filling in your details meanwhile.
          </p>
          <div className="step-progress-bar"><div className="step-progress-fill" style={{ width: `${Math.max(pct, 8)}%` }} /></div>
        </div>
      </div>
    );
  }
  if (job.status === "succeeded") {
    return compact ? null : (
      <div className="qr-job qr-job-ok" role="status">
        ✓ Found {job.result?.item_count ?? 0} items across {job.progress.total} page(s).
      </div>
    );
  }
  const failedPages = job.pages.filter((p) => p.status !== "succeeded");
  return (
    <div className={"qr-job " + (job.status === "partial" ? "qr-job-warn" : "qr-job-error")} role="alert">
      <strong>{job.status === "partial" ? "Some pages couldn't be read" : "We couldn't read your photos"}</strong>
      <p className="small">{job.error_message}</p>
      {!compact && failedPages.length > 0 && (
        <ul className="small">
          {failedPages.map((p) => (
            <li key={p.media_id}>Page {job.pages.indexOf(p) + 1}: {p.error}</li>
          ))}
        </ul>
      )}
      {error && <p className="error-text small">{error}</p>}
      {job.error_code !== "not_configured" && (
        <button type="button" className="btn btn-secondary" onClick={retry} disabled={retrying}>
          {retrying ? "Retrying…" : job.status === "partial" ? "Retry failed pages" : "Try again"}
        </button>
      )}
    </div>
  );
}
