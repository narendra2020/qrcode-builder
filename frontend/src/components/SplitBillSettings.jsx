import React, { useState } from "react";
import client, { errorMessage } from "../api/client";
import { fieldErrors } from "../api/stores";

/**
 * Split Bill switch + the payment details it relies on (UPI ID and payment
 * QR). Payment details are stored on the store, so other features can reuse
 * them — merchants enter them once.
 */
export default function SplitBillSettings({ store, setStore, meta }) {
  const payment = store.payment;
  const sb = payment.split_bill;
  const [upi, setUpi] = useState(payment.upi_id || "");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [errors, setErrors] = useState({});
  const [saved, setSaved] = useState("");

  async function call(label, fn) {
    setBusy(label);
    setError("");
    setErrors({});
    setSaved("");
    try {
      const { data } = await fn();
      setStore(data);
      setUpi(data.payment.upi_id || "");
      return data;
    } catch (err) {
      const fe = fieldErrors(err);
      if (Object.keys(fe).length) setErrors(fe);
      else setError(errorMessage(err));
      return null;
    } finally {
      setBusy("");
    }
  }

  const saveUpi = async (e) => {
    e.preventDefault();
    if (await call("upi", () => client.put(`/qr/stores/${store.id}/payment`, { upi_id: upi.trim() }))) setSaved("UPI ID saved.");
  };
  const toggle = () => call("toggle", () => client.put(`/qr/stores/${store.id}/payment`, { split_bill_enabled: !sb.enabled }));

  function pickQr(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > meta.max_upload_mb * 1024 * 1024) {
      setError(`Images must be ${meta.max_upload_mb} MB or smaller.`);
      return;
    }
    const form = new FormData();
    form.append("file", file);
    call("qr", () => client.post(`/qr/stores/${store.id}/payment/qr`, form)).then((d) => d && setSaved("Payment QR saved."));
  }
  const removeQr = () => {
    if (window.confirm("Remove your payment QR code?")) call("qr", () => client.delete(`/qr/stores/${store.id}/payment/qr`));
  };

  const live = store.status === "published";
  const upiDirty = upi.trim() !== (payment.upi_id || "");

  return (
    <section className="card" aria-labelledby="sb-title">
      <div className="qr-sb-head">
        <div>
          <h2 id="sb-title">Split Bill</h2>
          <p className="muted small">
            Let customers split the bill equally with friends. Each person gets their own amount and your payment
            details on WhatsApp.
          </p>
        </div>
        <button type="button" role="switch" aria-checked={sb.enabled} className={`qr-switch${sb.enabled ? " is-on" : ""}`}
          onClick={toggle} disabled={!!busy || (!sb.enabled && !!sb.blocker)} aria-label="Enable Split Bill">
          <span className="qr-switch-knob" />
        </button>
      </div>

      <p className={`small ${sb.active ? "success-text" : "muted"}`} role="status">
        {sb.active
          ? live ? "● On — customers see “Split Bill” on your store page." : "On — it will appear once your store is published."
          : sb.enabled ? "Turned on, but not available yet." : "Off — customers don't see Split Bill."}
      </p>
      {sb.usage && (
        sb.usage.unlimited
          ? <p className="muted small">Unlimited split bills on your plan.</p>
          : (
            <p className={`small ${sb.usage.remaining === 0 ? "error-text" : "muted"}`} role="status">
              {sb.usage.used} of {sb.usage.limit} split bills used this month.{" "}
              {sb.usage.remaining === 0 ? "Customers can't split bills until next month. " : ""}
              <a href={`/stores/${store.id}/upgrade`}>Upgrade to Pro for unlimited.</a>
            </p>
          )
      )}
      {!sb.enabled && sb.blocker && <p className="qr-job qr-job-warn small" role="note">{sb.blocker}</p>}
      {sb.enabled && sb.blocker && <p className="error-text small" role="alert">{sb.blocker}</p>}

      <h3 className="qr-subhead">Payment details</h3>
      <p className="muted small">Add at least one. Customers see these when they split a bill — they aren't shown on your public page.</p>

      <form onSubmit={saveUpi} noValidate>
        <div className="field-group">
          <label htmlFor="sb-upi">UPI ID</label>
          <div className="qr-inline-actions">
            <input id="sb-upi" type="text" value={upi} onChange={(e) => setUpi(e.target.value)} placeholder="yourrestaurant@okbank"
              maxLength={100} autoCapitalize="off" autoCorrect="off" spellCheck={false} aria-invalid={!!errors.upi_id}
              aria-describedby={errors.upi_id ? "sb-upi-err" : "sb-upi-hint"} />
            <button type="submit" className="btn btn-primary" disabled={!!busy || !upiDirty}>{busy === "upi" ? "Saving…" : "Save"}</button>
          </div>
          {errors.upi_id ? <p id="sb-upi-err" className="error-text small">{errors.upi_id}</p>
            : <p id="sb-upi-hint" className="muted small">With a UPI ID, each person's amount is pre-filled in their UPI app.</p>}
        </div>
      </form>

      <div className="field-group">
        <span className="qr-label">Payment QR code</span>
        <div className="qr-sb-qr">
          <div className="qr-logo-box qr-sb-qrbox">
            {payment.qr ? <img src={payment.qr.url} alt="Your payment QR code" /> : <span className="muted small">No QR yet</span>}
          </div>
          <div>
            <label className="btn btn-secondary">
              {busy === "qr" ? "Uploading…" : payment.qr ? "Replace QR" : "Upload QR"}
              <input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={pickQr} disabled={!!busy} />
            </label>
            {payment.qr && <button type="button" className="btn-link" onClick={removeQr} disabled={!!busy}>Remove</button>}
            <p className="muted small">
              Upload the QR from your UPI app. Without a UPI ID, customers must type their own amount after scanning it.
            </p>
            {errors.payment_qr && <p className="error-text small">{errors.payment_qr}</p>}
            {payment.qr_upi_hint && (
              <p className="small">
                This QR looks like it belongs to <strong>{payment.qr_upi_hint}</strong>.{" "}
                <button type="button" className="btn-link" onClick={() => setUpi(payment.qr_upi_hint)}>Use this UPI ID</button>
              </p>
            )}
          </div>
        </div>
      </div>

      {sb.delivery_mode === "manual" && (
        <p className="muted small" role="note">
          Automatic WhatsApp sending isn't set up for this platform yet, so customers will tap a WhatsApp button to send
          each person's message themselves.
        </p>
      )}
      {saved && <p className="success-text small" role="status">{saved}</p>}
      {error && <p className="error-text" role="alert">{error}</p>}
    </section>
  );
}
