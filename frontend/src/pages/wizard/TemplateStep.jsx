import React, { useEffect, useState } from "react";
import client, { errorMessage } from "../../api/client";
import { patchStore } from "../../api/stores";
import StorePreview from "../../components/StorePreview";
import { StepNav } from "./Wizard";

export default function TemplateStep({ store, setStore, onNext, onBack, embedded = false }) {
  const [templates, setTemplates] = useState([]);
  const [selected, setSelected] = useState(store.template_key);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    client.get(`/qr/stores/${store.id}/templates`).then(({ data }) => {
      setTemplates(data.templates);
      if (!selected && data.templates.length) setSelected(data.templates[0].key);
    });
  }, [store.id, store.category_key]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save() {
    setBusy(true);
    setError("");
    try {
      if (selected !== store.template_key) setStore(await patchStore(store.id, { template_key: selected }));
      onNext?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={embedded ? "" : "card"} aria-labelledby="tpl-title">
      {!embedded && (
        <>
          <h1 id="tpl-title">Choose your store design</h1>
          <p className="muted">
            Designs recommended for {store.category_label || "your business"} come first. Your items and branding carry over
            when you switch — change it any time.
          </p>
        </>
      )}
      <div className="qr-tpl-layout">
        <div className="qr-tpl-list" role="radiogroup" aria-label="Store designs">
          {templates.map((t, i) => (
            <button
              key={t.key}
              type="button"
              role="radio"
              aria-checked={selected === t.key}
              className={"qr-tpl-card" + (selected === t.key ? " is-selected" : "")}
              onClick={() => setSelected(t.key)}
            >
              <span className={`qr-tpl-swatch qr-tpl-swatch-${t.key}`} aria-hidden="true" />
              <span className="qr-tpl-text">
                <span className="template-name">
                  {t.name} {i === 0 && store.category_key && <span className="qr-badge">Recommended</span>}
                </span>
                <span className="template-description">{t.description}</span>
                <span className="qr-tpl-highlights">{t.highlights.join(" · ")}</span>
              </span>
            </button>
          ))}
        </div>
        {selected && <StorePreview storeId={store.id} template={selected} refreshKey={selected} title={`Preview of ${selected}`} />}
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {embedded ? (
        <button type="button" className="btn btn-primary" onClick={save} disabled={busy || selected === store.template_key}>
          {busy ? "Saving…" : "Use this design"}
        </button>
      ) : (
        <StepNav onBack={onBack} onNext={save} busy={busy} nextDisabled={!selected} />
      )}
    </section>
  );
}
