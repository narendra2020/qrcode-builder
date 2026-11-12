import React, { useState } from "react";
import client, { errorMessage } from "../api/client";
import ImageCropper from "./ImageCropper";
import StorePreview from "./StorePreview";

const COLORS = [
  ["primary", "Primary (buttons, prices)"],
  ["secondary", "Accent"],
  ["background", "Background"],
  ["text", "Text"],
];

/** Logo, banner, tagline, colours and font — shared by the wizard and dashboard. */
export default function BrandingForm({ store, setStore, meta, footer }) {
  const eff = store.branding.effective;
  const [values, setValues] = useState({
    primary: eff.primary, secondary: eff.secondary, background: eff.background, text: eff.text, font: eff.font,
    tagline: store.business.tagline || "",
  });
  const [cropping, setCropping] = useState(null); // { file, kind }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(0);

  async function uploadImage(kind, file, crop) {
    const form = new FormData();
    form.append("kind", kind);
    form.append("file", file);
    if (crop) {
      form.append("crop_x", crop.x);
      form.append("crop_y", crop.y);
      form.append("crop_w", crop.w);
      form.append("crop_h", crop.h);
    }
    setBusy(true);
    setError("");
    try {
      const { data: media } = await client.post(`/qr/stores/${store.id}/media`, form);
      const { data } = await client.put(`/qr/stores/${store.id}/branding`, { [`${kind}_media_id`]: media.id });
      setStore(data);
      setSaved((n) => n + 1);
    } catch (err) {
      setError(errorMessage(err, "Upload failed."));
    } finally {
      setBusy(false);
    }
  }

  function pick(kind) {
    return (e) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      if (file.size > meta.max_upload_mb * 1024 * 1024) {
        setError(`Images must be ${meta.max_upload_mb} MB or smaller.`);
        return;
      }
      setCropping({ file, kind });
    };
  }

  async function removeImage(kind) {
    setBusy(true);
    try {
      const { data } = await client.put(`/qr/stores/${store.id}/branding`, { [`${kind}_media_id`]: null });
      setStore(data);
      setSaved((n) => n + 1);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function save(reset = false) {
    setBusy(true);
    setError("");
    try {
      const body = reset ? { reset: true } : values;
      const { data } = await client.put(`/qr/stores/${store.id}/branding`, body);
      setStore(data);
      if (reset) {
        const e = data.branding.effective;
        setValues({ primary: e.primary, secondary: e.secondary, background: e.background, text: e.text, font: e.font, tagline: values.tagline });
      }
      setSaved((n) => n + 1);
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="qr-tpl-layout">
      <div>
        <div className="qr-brand-images">
          <div className="field-group">
            <span className="qr-label">Logo</span>
            <div className="qr-logo-box">
              {store.branding.logo ? <img src={store.branding.logo.url} alt="Your logo" /> :
                <span className="qr-logo-fallback" style={{ background: values.primary }}>{(store.name || "S")[0].toUpperCase()}</span>}
            </div>
            <div className="qr-inline-actions">
              <label className="btn btn-secondary">
                {store.branding.logo ? "Replace" : "Upload logo"}
                <input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={pick("logo")} />
              </label>
              {store.branding.logo && <button type="button" className="btn-link" onClick={() => removeImage("logo")}>Remove</button>}
            </div>
            {!store.branding.logo && <p className="muted small">No logo? We'll show your initial in your brand colour.</p>}
          </div>
          <div className="field-group">
            <span className="qr-label">Cover image (optional)</span>
            <div className="qr-banner-box">
              {store.branding.banner ? <img src={store.branding.banner.url} alt="Your cover" /> : <span className="muted small">No cover image</span>}
            </div>
            <div className="qr-inline-actions">
              <label className="btn btn-secondary">
                {store.branding.banner ? "Replace" : "Upload cover"}
                <input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={pick("banner")} />
              </label>
              {store.branding.banner && <button type="button" className="btn-link" onClick={() => removeImage("banner")}>Remove</button>}
            </div>
          </div>
        </div>

        <div className="field-group">
          <label htmlFor="br-tagline">Tagline</label>
          <input id="br-tagline" type="text" maxLength={160} placeholder="e.g. Fresh South Indian breakfast since 1998"
            value={values.tagline} onChange={(e) => setValues((v) => ({ ...v, tagline: e.target.value }))} />
        </div>

        <div className="qr-colors">
          {COLORS.map(([k, label]) => (
            <div key={k} className="qr-color">
              <label htmlFor={`br-${k}`}>{label}</label>
              <div className="qr-inline-actions">
                <input id={`br-${k}`} type="color" value={values[k]} onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))} />
                <code className="small">{values[k]}</code>
              </div>
            </div>
          ))}
        </div>

        <div className="field-group">
          <label htmlFor="br-font">Font</label>
          <select id="br-font" value={values.font} onChange={(e) => setValues((v) => ({ ...v, font: e.target.value }))}>
            {meta.fonts.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>

        {store.branding.warnings?.map((w) => <p key={w} className="muted small">ℹ️ {w}</p>)}
        {error && <p className="error-text" role="alert">{error}</p>}

        <div className="qr-inline-actions">
          <button type="button" className="btn btn-secondary" onClick={() => save(false)} disabled={busy}>
            {busy ? "Saving…" : "Apply & preview"}
          </button>
          <button type="button" className="btn-link" onClick={() => save(true)} disabled={busy}>Reset to design defaults</button>
        </div>
        {footer?.({ save: () => save(false), busy })}
      </div>

      <StorePreview storeId={store.id} refreshKey={saved} title="Branding preview" />

      {cropping && (
        <ImageCropper
          file={cropping.file}
          aspect={cropping.kind === "logo" ? 1 : 16 / 7}
          title={cropping.kind === "logo" ? "Crop your logo" : "Crop your cover image"}
          onCancel={() => setCropping(null)}
          onConfirm={(crop) => {
            const { file, kind } = cropping;
            setCropping(null);
            uploadImage(kind, file, crop);
          }}
        />
      )}
    </div>
  );
}
