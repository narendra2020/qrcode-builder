import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import client, { errorMessage } from "../api/client";

const RAZORPAY_SCRIPT_SRC = "https://checkout.razorpay.com/v1/checkout.js";

function loadRazorpayScript() {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = RAZORPAY_SCRIPT_SRC;
    script.onload = resolve;
    script.onerror = reject;
    document.body.appendChild(script);
  });
}

// Offers still worth buying given the current plan (Pro + Split Bill is the top tier).
function offersFor(data) {
  const cur = data.current.code;
  const all = data.offers || [];
  if (cur === "pro_split") return [];
  if (cur === "pro" || cur === "split_bill") return all.filter((o) => o.plan_code === "pro_split");
  return all;
}

/**
 * Upgrade to the QR Store "Pro" plan via MePage's existing billing
 * (/api/billing: signature-verified Razorpay or admin-reviewed UPI claim).
 * The plan only becomes active once billing marks the payment approved —
 * this page never assumes success on its own.
 */
export default function Upgrade() {
  const { storeId } = useParams();
  const [plans, setPlans] = useState(null);
  const [billing, setBilling] = useState(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [screenshot, setScreenshot] = useState(null);
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState(null); // "pending" | "active"
  const [method, setMethod] = useState(null);
  const [chosen, setChosen] = useState(null); // product being bought

  function load() {
    Promise.all([client.get("/qr/plans"), client.get("/billing/status")])
      .then(([p, b]) => {
        setPlans(p.data);
        setBilling(b.data);
        setMethod((m) => m || (b.data.razorpay_enabled ? "razorpay" : "upi"));
        setChosen((c) => (offersFor(p.data).some((o) => o.product === c) ? c : offersFor(p.data)[0]?.product || null));
        setState(offersFor(p.data).length ? null : "active");
      })
      .catch((err) => setError(errorMessage(err, "Could not load plans.")));
  }
  useEffect(load, []);

  if (error && !plans) return <div className="card"><p className="error-text">{error}</p></div>;
  if (!plans || !billing) return <div className="card"><p className="muted">Loading plans…</p></div>;
  const offers = offersFor(plans);
  const offer = offers.find((o) => o.product === chosen) || offers[0];
  const product = offer?.product;
  const planName = (code) => plans.plans.find((p) => p.code === code)?.name || code;

  async function payOnline() {
    setBusy(true);
    setError("");
    try {
      await loadRazorpayScript();
      const { data: order } = await client.post("/billing/razorpay/order", { product });
      new window.Razorpay({
        key: order.key_id,
        amount: order.amount,
        currency: order.currency,
        order_id: order.order_id,
        name: "MePage",
        description: `${planName(offer.plan_code)} — 1 year`,
        handler: async (response) => {
          try {
            await client.post("/billing/razorpay/verify", response);
            load();
          } catch (err) {
            setError(errorMessage(err, "Payment verification failed. Contact support if you were charged."));
          } finally {
            setBusy(false);
          }
        },
        modal: { ondismiss: () => setBusy(false) },
      }).open();
    } catch (err) {
      setError(errorMessage(err, "Could not start online payment. Please try again."));
      setBusy(false);
    }
  }

  async function submitClaim(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await client.post("/billing/payment-requests", { reference_note: note || null, product });
      if (screenshot) {
        const form = new FormData();
        form.append("file", screenshot);
        await client.post(`/billing/payment-requests/${res.data.id}/screenshot`, form);
      }
      setState("pending");
    } catch (err) {
      setError(errorMessage(err, "Could not submit payment details."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <Link to={storeId ? `/stores/${storeId}` : "/"} className="btn-link">← Back</Link>
      <h1>Upgrade your store plan</h1>
      <p className="muted">Choose Split Bill, Pro, or both together.</p>

      <div className="qr-plans" role="radiogroup" aria-label="Choose a plan">
        {plans.plans.map((p) => {
          const o = offers.find((x) => x.plan_code === p.code);
          const selected = !!o && o.product === product;
          const price = o?.price_rupees ?? p.price_rupees;
          return (
            <div
              key={p.code}
              className={"qr-plan" + (plans.current.code === p.code ? " is-current" : "") + (o ? " is-selectable" : "") + (selected ? " is-selected" : "")}
              {...(o ? {
                role: "radio", tabIndex: 0, "aria-checked": selected,
                onClick: () => setChosen(o.product),
                onKeyDown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setChosen(o.product); } },
              } : {})}
            >
              <h2>{p.name}</h2>
              <p className="qr-big">{price ? `₹${price}` : p.code === "free" ? "Free" : "—"}
                {price ? <span className="muted small"> / year</span> : null}</p>
              <p className="muted small">{p.description}</p>
              <ul className="small">{p.features.map((f) => <li key={f}>{f}</li>)}</ul>
              {plans.current.code === p.code && <span className="qr-badge">Current plan</span>}
              {selected && <span className="qr-badge qr-badge-selected">Selected</span>}
            </div>
          );
        })}
      </div>

      {state === "active" ? (
        <p className="success-text">Your {planName(plans.current.code)} plan is active. You're on our top plan — nothing more to buy.</p>
      ) : state === "pending" ? (
        <p className="muted">Thanks! Your payment details are with our team for verification. Your plan upgrades as soon as it's approved — usually within one business day.</p>
      ) : !offer ? (
        <p className="muted">Upgrades aren't available yet. Please contact MePage support for a higher limit.</p>
      ) : billing.pending_request ? (
        <p className="muted">You already have a payment claim awaiting review.</p>
      ) : (
        <div className="field-group">
          <h2>Pay ₹{offer.price_rupees} for 1 year — {planName(offer.plan_code)}</h2>
          {billing.upi_enabled && billing.razorpay_enabled && (
            <div className="qr-seg" role="group" aria-label="Payment method">
              <button type="button" aria-pressed={method === "razorpay"} onClick={() => setMethod("razorpay")}>Pay online</button>
              <button type="button" aria-pressed={method === "upi"} onClick={() => setMethod("upi")}>UPI QR</button>
            </div>
          )}
          {method === "razorpay" && billing.razorpay_enabled ? (
            <>
              <p className="muted small">Card, UPI, netbanking or wallet via Razorpay. Your plan activates once the payment is confirmed.</p>
              <button type="button" className="btn btn-primary" onClick={payOnline} disabled={busy}>{busy ? "Processing…" : "Pay online"}</button>
            </>
          ) : billing.upi_enabled ? (
            <>
              {billing.qr_image_url ? <img src={billing.qr_image_url} alt="UPI QR code" style={{ maxWidth: 220 }} /> : <p className="muted small">UPI QR not configured yet.</p>}
              {billing.upi_id && <p className="small">UPI ID: <strong>{billing.upi_id}</strong></p>}
              <p className="muted small">After paying, share your reference below. Our team verifies it and then activates your plan.</p>
              <form onSubmit={submitClaim} className="qr-stack">
                <label htmlFor="up-ref">UTR / transaction reference</label>
                <input id="up-ref" type="text" value={note} onChange={(e) => setNote(e.target.value)} />
                <label htmlFor="up-shot">Payment screenshot (optional)</label>
                <input id="up-shot" type="file" accept="image/*" onChange={(e) => setScreenshot(e.target.files?.[0] || null)} />
                <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Submitting…" : "I've paid — submit for review"}</button>
              </form>
            </>
          ) : (
            <p className="muted">No payment method is enabled right now. Please contact support.</p>
          )}
        </div>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}
    </div>
  );
}
