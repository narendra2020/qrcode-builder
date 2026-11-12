import React, { useState } from "react";
import client, { errorMessage } from "../api/client";

/**
 * Verifies a business WhatsApp number that differs from the owner's
 * login number, using MePage's existing WhatsApp OTP service
 * (/api/auth/number-verification/*). The resulting proof token is handed
 * to the store API, which only then enables the number for enquiries.
 */
export default function WhatsappVerify({ storeId, phone, onVerified, onCancel }) {
  const [txn, setTxn] = useState(null);
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function send() {
    setBusy(true);
    setError("");
    try {
      const { data } = await client.post("/auth/number-verification/start", { phone, purpose: "qr_whatsapp" });
      setTxn(data.transaction_id);
    } catch (err) {
      setError(errorMessage(err, "Couldn't send the code. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { data } = await client.post("/auth/number-verification/confirm", { transaction_id: txn, otp });
      const res = await client.post(`/qr/stores/${storeId}/whatsapp/verify`, { proof_token: data.proof_token });
      onVerified(res.data);
    } catch (err) {
      setError(errorMessage(err, "Invalid or expired code."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="qr-verify" role="group" aria-label="Verify WhatsApp number">
      {!txn ? (
        <>
          <p className="small">
            To make sure enquiries reach you, we'll send a 6-digit code on WhatsApp to <strong>{phone}</strong>.
          </p>
          <div className="qr-inline-actions">
            <button type="button" className="btn btn-primary" onClick={send} disabled={busy}>
              {busy ? "Sending…" : "Send code"}
            </button>
            <button type="button" className="btn-link" onClick={onCancel}>Cancel</button>
          </div>
        </>
      ) : (
        <form onSubmit={confirm} className="qr-inline-actions">
          <label htmlFor="wa-otp" className="sr-only">Code</label>
          <input id="wa-otp" type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="6-digit code"
            value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} />
          <button type="submit" className="btn btn-primary" disabled={busy || otp.length !== 6}>
            {busy ? "Verifying…" : "Verify"}
          </button>
          <button type="button" className="btn-link" onClick={send} disabled={busy}>Resend</button>
        </form>
      )}
      {error && <p className="error-text small" role="alert">{error}</p>}
    </div>
  );
}
