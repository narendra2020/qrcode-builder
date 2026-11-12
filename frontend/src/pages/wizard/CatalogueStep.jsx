import React, { useState } from "react";
import client, { errorMessage } from "../../api/client";
import CatalogueEditor from "../../components/CatalogueEditor";
import JobStatus from "../../components/JobStatus";
import useJobPolling from "./useJobPolling";
import { StepNav } from "./Wizard";

export default function CatalogueStep({ store, setStore, reload, meta, onNext, onBack }) {
  const running = useJobPolling(store, setStore);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  const [editorKey, setEditorKey] = useState(0);
  const category = meta.categories.find((c) => c.key === store.category_key);
  const job = store.job;
  const hasResults = job && ["succeeded", "partial"].includes(job.status) && job.result?.item_count > 0;
  const neverImported = store.item_count === 0;

  async function runImport(mode) {
    if (mode === "replace" && store.item_count > 0 &&
        !window.confirm("Replace the AI-extracted items with a fresh import? Items you added or edited yourself are kept.")) return;
    setImporting(true);
    setError("");
    try {
      await client.post(`/qr/stores/${store.id}/catalogue/import`, { mode });
      localStorage.removeItem(`qr-draft:${store.id}`);
      await reload();
      setEditorKey((k) => k + 1);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setImporting(false);
    }
  }

  return (
    <section className="card" aria-labelledby="items-title">
      <h1 id="items-title">Review your {category?.catalogue_noun?.toLowerCase() || "catalogue"}</h1>
      <p className="muted">
        Check every name and price — the AI copies only what's printed and never guesses missing prices. Add photos, mark
        items unavailable, or add anything it missed.
      </p>

      <JobStatus store={store} setStore={setStore} />

      {running && neverImported && (
        <p className="muted">Your items will appear here once reading finishes. You can also start adding items yourself.</p>
      )}

      {hasResults && (
        <div className="qr-banner">
          {neverImported ? (
            <>
              <strong>{job.result.item_count} items found.</strong>{" "}
              <button type="button" className="btn btn-primary" onClick={() => runImport("replace")} disabled={importing}>
                {importing ? "Adding…" : "Add them to my catalogue"}
              </button>
            </>
          ) : (
            <span className="small">
              Re-ran the AI or added more pages?{" "}
              <button type="button" className="btn-link" onClick={() => runImport("replace")} disabled={importing}>Re-import extracted items</button>
              {" · "}
              <button type="button" className="btn-link" onClick={() => runImport("append")} disabled={importing}>Append instead</button>
            </span>
          )}
        </div>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}

      <CatalogueEditor
        key={editorKey}
        storeId={store.id}
        meta={meta}
        category={category}
        isLive={false}
        onSaved={() => reload()}
      />

      <StepNav
        onBack={onBack}
        onNext={onNext}
        nextDisabled={store.item_count === 0}
        hint={store.item_count === 0 ? "Save at least one item to continue" : store.review_count ? `${store.review_count} item(s) still need review` : null}
      />
    </section>
  );
}
