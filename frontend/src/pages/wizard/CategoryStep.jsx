import React, { useEffect, useState } from "react";
import { patchStore } from "../../api/stores";
import { errorMessage } from "../../api/client";
import JobStatus from "../../components/JobStatus";
import useJobPolling from "./useJobPolling";
import { StepNav } from "./Wizard";

export default function CategoryStep({ store, setStore, meta, onNext, onBack }) {
  const running = useJobPolling(store, setStore);
  const suggestion = store.job?.result?.category;
  const [selected, setSelected] = useState(store.category_key || suggestion?.suggested || null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Preselect the AI's suggestion when it arrives (never override an owner's choice).
  useEffect(() => {
    if (!store.category_key && !selected && suggestion?.suggested) setSelected(suggestion.suggested);
  }, [suggestion?.suggested, store.category_key, selected]);

  const byKey = Object.fromEntries(meta.categories.map((c) => [c.key, c]));
  const alternatives = (suggestion?.alternatives || []).map((a) => byKey[a.key]).filter(Boolean);
  const current = selected ? byKey[selected] : null;

  async function next() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      if (selected !== store.category_key) setStore(await patchStore(store.id, { category_key: selected }));
      onNext();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="cat-title">
      <h1 id="cat-title">What kind of business is this?</h1>
      <JobStatus store={store} setStore={setStore} compact />

      {running && <p className="muted">We'll suggest a category as soon as your photo is read. You can also pick one now.</p>}

      {current && (
        <div className="qr-cat-selected" aria-live="polite">
          <span className="qr-cat-icon" aria-hidden="true">{current.icon}</span>
          <div>
            <p className="qr-eyebrow">
              {selected === suggestion?.suggested && !suggestion?.low_confidence ? "Suggested by AI" : selected === suggestion?.suggested ? "AI's best guess" : "Your choice"}
            </p>
            <h2>{current.label}</h2>
            <p className="muted small">{current.description}</p>
            {selected === suggestion?.suggested && suggestion?.evidence && (
              <p className="muted small">Why: {suggestion.evidence}</p>
            )}
          </div>
        </div>
      )}

      {suggestion && (suggestion.low_confidence || suggestion.insufficient_evidence) && (
        <div className="qr-job qr-job-warn" role="note">
          <strong>{suggestion.insufficient_evidence ? "We couldn't tell from the photo" : "We're not fully sure"}</strong>
          <p className="small">
            {suggestion.clarifying_question || "Please choose the category that best describes your business."}
          </p>
          {alternatives.length > 0 && (
            <div className="qr-chip-row">
              <span className="small muted">It might also be:</span>
              {alternatives.map((c) => (
                <button key={c.key} type="button" className="qr-chip" onClick={() => setSelected(c.key)}>
                  {c.icon} {c.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <fieldset className="qr-cat-grid">
        <legend className="muted small">{current ? "Change category" : "Choose a category"}</legend>
        {meta.categories.map((c) => (
          <label key={c.key} className={"qr-cat-card" + (selected === c.key ? " is-selected" : "")}>
            <input type="radio" name="category" value={c.key} checked={selected === c.key} onChange={() => setSelected(c.key)} />
            <span className="qr-cat-icon" aria-hidden="true">{c.icon}</span>
            <span className="qr-cat-label">{c.label}</span>
            {suggestion?.suggested === c.key && <span className="qr-badge">AI pick</span>}
          </label>
        ))}
      </fieldset>

      {error && <p className="error-text" role="alert">{error}</p>}
      <StepNav onBack={onBack} onNext={next} nextDisabled={!selected} busy={busy} hint={!selected ? "Choose a category" : null} />
    </section>
  );
}
