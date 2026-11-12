import React, { useEffect, useRef, useState } from "react";
import client, { errorMessage } from "../api/client";
import { fieldErrors, patchStore } from "../api/stores";
import WhatsappVerify from "./WhatsappVerify";

const FIELDS = ["name", "address_line", "city", "state", "postal_code", "country", "contact_phone",
  "whatsapp_number", "email", "description", "opening_hours", "maps_url", "zomato_url", "swiggy_url"];

/**
 * Business information form, shared by the wizard and the dashboard.
 * AI-read details are offered as one-tap suggestions (never auto-filled
 * into the address), and nothing is invented.
 */
export default function BusinessForm({ store, setStore, extracted, onSaved, submitLabel = "Save", footer }) {
  const [values, setValues] = useState(() => {
    const v = {};
    FIELDS.forEach((k) => (v[k] = store.business[k] || ""));
    if (!v.name && extracted?.name) v.name = extracted.name;
    if (!v.opening_hours && extracted?.opening_hours) v.opening_hours = extracted.opening_hours;
    return v;
  });
  const [slug, setSlug] = useState(store.slug || "");
  const [slugState, setSlugState] = useState(null);
  const [slugTouched, setSlugTouched] = useState(!!store.slug);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const slugLocked = !!store.first_published_at;
  const timer = useRef(null);

  const set = (k) => (e) => setValues((v) => ({ ...v, [k]: e.target.value }));

  // Suggest a slug from the store name until the owner edits it.
  useEffect(() => {
    if (slugTouched || slugLocked || !values.name.trim()) return undefined;
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try {
        const { data } = await client.get(`/qr/stores/${store.id}/slug-suggestion`, { params: { name: values.name } });
        if (data.slug) setSlug(data.slug);
      } catch {
        /* ignore */
      }
    }, 400);
    return () => clearTimeout(timer.current);
  }, [values.name, slugTouched, slugLocked, store.id]);

  // Live availability check.
  useEffect(() => {
    if (slugLocked || !slug) {
      setSlugState(null);
      return undefined;
    }
    const t = setTimeout(async () => {
      try {
        const { data } = await client.get(`/qr/stores/${store.id}/slug-availability`, { params: { slug } });
        setSlugState(data);
      } catch {
        setSlugState(null);
      }
    }, 350);
    return () => clearTimeout(t);
  }, [slug, slugLocked, store.id]);

  const whatsappChanged = values.whatsapp_number && normalizeDigits(values.whatsapp_number) !== normalizeDigits(store.business.whatsapp_number || "");
  const needsVerification = whatsappChanged && normalizeDigits(values.whatsapp_number) !== normalizeDigits(store.owner_number || "");

  function validate() {
    const e = {};
    if (!values.name.trim()) e.name = "Store name is required.";
    if (!slugLocked && (!slug || (slugState && !slugState.available))) e.slug = slugState?.message || "Choose a store address.";
    if (!values.whatsapp_number.trim()) e.whatsapp_number = "A WhatsApp number is required to receive enquiries.";
    if (values.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(values.email)) e.email = "Enter a valid email address.";
    if (values.maps_url && !/^https:\/\//.test(values.maps_url)) e.maps_url = "Paste the full https:// link from Google Maps.";
    if (values.postal_code && !/^[A-Za-z0-9 -]{3,10}$/.test(values.postal_code)) e.postal_code = "Enter a valid postal code.";
    if (values.zomato_url && !/^https:\/\//.test(values.zomato_url)) e.zomato_url = "Paste the full https:// Zomato link.";
    if (values.swiggy_url && !/^https:\/\//.test(values.swiggy_url)) e.swiggy_url = "Paste the full https:// Swiggy link.";
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  async function save(ev) {
    ev?.preventDefault();
    setError("");
    if (!validate()) return;
    if (needsVerification) {
      setVerifying(true);
      return;
    }
    setBusy(true);
    try {
      const body = {};
      FIELDS.forEach((k) => {
        const val = values[k].trim();
        if (val !== (store.business[k] || "")) body[k] = val || null;
      });
      if (body.whatsapp_number === undefined) delete body.whatsapp_number;
      if (!slugLocked && slug !== store.slug) body.slug = slug;
      const data = Object.keys(body).length ? await patchStore(store.id, body) : store;
      setStore(data);
      onSaved?.(data);
    } catch (err) {
      const fe = fieldErrors(err);
      if (err.response?.status === 428) {
        setVerifying(true);
      } else if (Object.keys(fe).length) {
        setErrors(fe);
        if (err.response?.data?.detail?.suggestions) setSlugState(err.response.data.detail);
      } else setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const field = (k, label, props = {}) => (
    <div className="field-group">
      <label htmlFor={`bf-${k}`}>
        {label}
        {props.required && <span className="required-mark" aria-hidden="true">*</span>}
      </label>
      {props.textarea ? (
        <textarea id={`bf-${k}`} rows={props.rows || 3} value={values[k]} onChange={set(k)} aria-invalid={!!errors[k]}
          aria-describedby={errors[k] ? `bf-${k}-err` : undefined} placeholder={props.placeholder} maxLength={props.maxLength} />
      ) : (
        <input id={`bf-${k}`} type={props.type || "text"} value={values[k]} onChange={set(k)} aria-invalid={!!errors[k]}
          aria-describedby={errors[k] ? `bf-${k}-err` : props.hint ? `bf-${k}-hint` : undefined}
          placeholder={props.placeholder} autoComplete={props.autoComplete} inputMode={props.inputMode} maxLength={props.maxLength} />
      )}
      {props.hint && !errors[k] && <p id={`bf-${k}-hint`} className="muted small">{props.hint}</p>}
      {errors[k] && <p id={`bf-${k}-err`} className="error-text small">{errors[k]}</p>}
    </div>
  );

  const aiFacts = extracted && ["phone", "address", "email", "tagline"].filter((k) => extracted[k]);

  return (
    <form onSubmit={save} noValidate>
      {aiFacts?.length > 0 && (
        <div className="qr-ai-facts">
          <p className="small"><strong>Read from your photo</strong> — tap to use (please double-check):</p>
          <div className="qr-chip-row">
            {extracted.phone && <button type="button" className="qr-chip" onClick={() => setValues((v) => ({ ...v, contact_phone: extracted.phone }))}>📞 {extracted.phone}</button>}
            {extracted.address && <button type="button" className="qr-chip" onClick={() => setValues((v) => ({ ...v, address_line: extracted.address }))}>📍 {extracted.address}</button>}
            {extracted.email && <button type="button" className="qr-chip" onClick={() => setValues((v) => ({ ...v, email: extracted.email }))}>✉️ {extracted.email}</button>}
          </div>
        </div>
      )}

      <div className="qr-form-grid">
        {field("name", "Store or business name", { required: true, maxLength: 120, autoComplete: "organization" })}
        <div className="field-group">
          <label htmlFor="bf-slug">Store web address<span className="required-mark" aria-hidden="true">*</span></label>
          <div className="subdomain-input-row">
            <input id="bf-slug" type="text" value={slug} disabled={slugLocked} maxLength={63}
              onChange={(e) => { setSlugTouched(true); setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "")); }}
              aria-invalid={!!errors.slug} aria-describedby="bf-slug-status" />
            <span className="subdomain-suffix">.{store.base_domain}</span>
          </div>
          <div id="bf-slug-status" aria-live="polite">
            {slugLocked ? (
              <p className="muted small">Fixed after publishing so printed QR codes keep working.</p>
            ) : errors.slug ? (
              <p className="error-text small">{errors.slug}</p>
            ) : slugState ? (
              slugState.available ? <p className="success-text small">✓ {slug}.{store.base_domain} is available</p>
                : <p className="error-text small">{slugState.message}</p>
            ) : null}
            {slugState?.suggestions?.length > 0 && !slugLocked && (
              <div className="qr-chip-row">
                <span className="muted small">Try:</span>
                {slugState.suggestions.map((s) => (
                  <button key={s} type="button" className="qr-chip" onClick={() => { setSlugTouched(true); setSlug(s); }}>{s}</button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <h3 className="qr-subhead">WhatsApp for enquiries</h3>
      <div className="qr-form-grid">
        <div className="field-group">
          <label htmlFor="bf-whatsapp_number">WhatsApp enquiry number<span className="required-mark" aria-hidden="true">*</span></label>
          <input id="bf-whatsapp_number" type="tel" inputMode="tel" autoComplete="tel" value={values.whatsapp_number}
            onChange={(e) => { set("whatsapp_number")(e); setVerifying(false); }} placeholder="+91 98765 43210"
            aria-invalid={!!errors.whatsapp_number} aria-describedby="bf-wa-hint" />
          <p id="bf-wa-hint" className="muted small">
            {store.business.whatsapp_verified && !whatsappChanged
              ? "✓ Verified — customer enquiries will open a chat with this number."
              : "Defaults to your verified login number. A different number needs a quick WhatsApp code check."}
          </p>
          {errors.whatsapp_number && <p className="error-text small">{errors.whatsapp_number}</p>}
          {verifying && needsVerification && (
            <WhatsappVerify storeId={store.id} phone={values.whatsapp_number} onCancel={() => setVerifying(false)}
              onVerified={(data) => { setStore(data); setVerifying(false); setValues((v) => ({ ...v, whatsapp_number: data.business.whatsapp_number })); }} />
          )}
        </div>
        {field("contact_phone", "Contact phone (optional)", { type: "tel", inputMode: "tel", placeholder: "+91 …", hint: "Shown as a Call button." })}
      </div>

      <h3 className="qr-subhead">Location</h3>
      {field("address_line", "Address", { autoComplete: "street-address", maxLength: 255, placeholder: "Shop no., street, area" })}
      <div className="qr-form-grid qr-form-grid-4">
        {field("city", "City", { autoComplete: "address-level2", maxLength: 100 })}
        {field("state", "State", { autoComplete: "address-level1", maxLength: 100 })}
        {field("postal_code", "PIN code", { autoComplete: "postal-code", inputMode: "numeric", maxLength: 10 })}
        {field("country", "Country", { autoComplete: "country-name", maxLength: 100, placeholder: "India" })}
      </div>
      {field("maps_url", "Google Maps link (optional)", { type: "url", placeholder: "https://maps.app.goo.gl/…", hint: "Shown as a Directions button." })}

      {store.delivery_links_supported && (
        <>
          <h3 className="qr-subhead">Food delivery (optional)</h3>
          <div className="qr-form-grid">
            {field("zomato_url", "Zomato link", { type: "url", placeholder: "https://www.zomato.com/…", hint: "Shows an “Order on Zomato” button." })}
            {field("swiggy_url", "Swiggy link", { type: "url", placeholder: "https://www.swiggy.com/…", hint: "Shows an “Order on Swiggy” button." })}
          </div>
        </>
      )}

      <h3 className="qr-subhead">About (optional)</h3>
      <div className="qr-form-grid">
        {field("email", "Email", { type: "email", autoComplete: "email", maxLength: 255 })}
        {field("opening_hours", "Opening hours", { textarea: true, rows: 2, maxLength: 500, placeholder: "Mon–Sat 10am–9pm" })}
      </div>
      {field("description", "Short description", { textarea: true, maxLength: 2000, placeholder: "What makes your store special?" })}

      {error && <p className="error-text" role="alert">{error}</p>}
      {footer ? footer({ save, busy }) : (
        <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : submitLabel}</button>
      )}
    </form>
  );
}

function normalizeDigits(v) {
  const d = (v || "").replace(/\D/g, "");
  return d.length === 10 ? "91" + d : d.replace(/^0+/, "");
}
