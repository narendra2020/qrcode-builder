import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import client, { errorMessage } from "../../api/client";
import QrPanel from "../../components/QrPanel";
import StorePreview from "../../components/StorePreview";

export default function ReviewStep({ store, setStore, meta, onBack, goTo }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [issues, setIssues] = useState(store.readiness);
  const [published, setPublished] = useState(store.status === "published");
  const category = meta.categories.find((c) => c.key === store.category_key);
  const template = meta.templates.find((t) => t.key === store.template_key);
  const b = store.business;
  const address = [b.address_line, b.city, b.state, b.postal_code].filter(Boolean).join(", ");

  async function publish() {
    setBusy(true);
    setError("");
    try {
      const { data } = await client.post(`/qr/stores/${store.id}/publish`);
      setStore(data);
      setPublished(true);
      window.scrollTo({ top: 0 });
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (detail?.issues) setIssues(detail.issues);
      setError(errorMessage(err, "Publishing failed. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  if (published) {
    return (
      <section className="card qr-success" aria-labelledby="pub-title">
        <p className="qr-success-icon" aria-hidden="true">🎉</p>
        <h1 id="pub-title">{store.name} is live!</h1>
        <p className="muted">Share your link or print the QR code. Customers can browse and send enquiries straight to your WhatsApp.</p>
        <QrPanel store={store} live />
        <div className="qr-inline-actions" style={{ justifyContent: "center", marginTop: "1rem" }}>
          <button className="btn btn-primary" onClick={() => navigate(`/stores/${store.id}`)}>Go to dashboard</button>
        </div>
      </section>
    );
  }

  return (
    <section className="card" aria-labelledby="review-title">
      <h1 id="review-title">Review & publish</h1>
      <div className="qr-tpl-layout">
        <div>
          <dl className="qr-summary">
            <SummaryRow label="Store" value={store.name} onEdit={() => goTo("business")} />
            <SummaryRow label="Category" value={category ? `${category.icon} ${category.label}` : "—"} onEdit={() => goTo("category")} />
            <SummaryRow label="Address" value={address || "Not added (optional)"} onEdit={() => goTo("business")} />
            <SummaryRow label="WhatsApp enquiries" value={b.whatsapp_number ? `${b.whatsapp_number}${b.whatsapp_verified ? " ✓ verified" : " — not verified"}` : "—"} onEdit={() => goTo("business")} />
            <SummaryRow label="Design" value={template?.name || "—"} onEdit={() => goTo("template")} />
            <SummaryRow label="Items" value={`${store.item_count} item(s)${store.review_count ? ` · ${store.review_count} need review` : ""}`} onEdit={() => goTo("catalogue")} />
            <SummaryRow label="Branding" value={store.branding.logo ? "Logo added" : "Default branding"} onEdit={() => goTo("branding")} />
          </dl>

          <h2 className="qr-subhead">Your link & QR code</h2>
          <QrPanel store={store} live={false} />

          <div className="qr-howto small">
            <p><strong>How customers order</strong></p>
            <ul>
              <li>Tap <em>Enquire</em> on an item to open WhatsApp with that item's name and price filled in.</li>
              <li>Or add several items to the list and send them in one WhatsApp message.</li>
              <li>The message goes to {b.whatsapp_number || "your WhatsApp"} only when the customer presses Send.</li>
            </ul>
          </div>

          {issues.length > 0 && (
            <div className="qr-job qr-job-warn" role="alert">
              <strong>Before you publish:</strong>
              <ul className="small">
                {issues.map((i) => (
                  <li key={i.message}>
                    {i.message} <button type="button" className="btn-link" onClick={() => goTo(i.step)}>Fix</button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {error && <p className="error-text" role="alert">{error}</p>}
          <div className="qr-step-nav">
            <button type="button" className="btn btn-secondary" onClick={onBack} disabled={busy}>Back</button>
            <button type="button" className="btn btn-primary" onClick={publish} disabled={busy || issues.length > 0}>
              {busy ? "Publishing…" : "Publish my store"}
            </button>
          </div>
        </div>
        <StorePreview storeId={store.id} refreshKey={store.item_count} title="Final preview" />
      </div>
    </section>
  );
}

function SummaryRow({ label, value, onEdit }) {
  return (
    <div className="qr-summary-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
      <dd><button type="button" className="btn-link" onClick={onEdit} aria-label={`Edit ${label}`}>Edit</button></dd>
    </div>
  );
}
