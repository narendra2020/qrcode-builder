import React, { useEffect, useState } from "react";
import client from "../api/client";
import { downloadFile } from "../api/stores";
import TableQrManager from "./TableQrManager";

/** Branded QR preview + PNG/SVG, print/digital downloads + share actions. */
export default function QrPanel({ store, live }) {
  const [src, setSrc] = useState(null);
  const [copied, setCopied] = useState(false);
  const url = store.public_url;

  useEffect(() => {
    if (!store.slug) return undefined;
    let href = null;
    client
      .get(`/qr/stores/${store.id}/qr`, { params: { format: "png", layout: "card" }, responseType: "blob" })
      .then((res) => {
        href = URL.createObjectURL(res.data);
        setSrc(href);
      })
      .catch(() => setSrc(null));
    return () => href && URL.revokeObjectURL(href);
  }, [store.id, store.slug, store.name, store.branding?.effective?.primary]);

  if (!store.slug) return <p className="muted small">Choose your store address to get your QR code.</p>;

  const dl = (format, layout, size) =>
    downloadFile(`/qr/stores/${store.id}/qr?format=${format}&layout=${layout}&size=${size}`,
      `${store.slug}-qr-${layout}${size === "print" ? "-print" : ""}.${format}`);

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("Copy your store link:", url);
    }
  }

  async function share() {
    if (navigator.share) {
      try {
        await navigator.share({ title: store.name, text: `Browse ${store.name} and enquire on WhatsApp`, url });
      } catch {
        /* cancelled */
      }
    } else copy();
  }

  const waShare = `https://wa.me/?text=${encodeURIComponent(`Browse ${store.name} and enquire on WhatsApp: ${url}`)}`;

  return (
    <div className="qr-panel">
      <div className="qr-panel-img">
        {src ? <img src={src} alt={`QR code for ${url}`} /> : <div className="qr-panel-ph"><span className="qr-spinner" aria-hidden="true" /></div>}
      </div>
      <div className="qr-panel-body">
        <p className="qr-url">
          {live ? <a href={url} target="_blank" rel="noopener noreferrer">{url.replace("https://", "")}</a> : <span>{url.replace("https://", "")}</span>}
          {!live && <span className="qr-badge qr-badge-muted">Not live yet</span>}
        </p>
        <div className="qr-inline-actions">
          <button type="button" className="btn btn-secondary" onClick={copy}>{copied ? "Copied ✓" : "Copy link"}</button>
          {live && <button type="button" className="btn btn-secondary" onClick={share}>Share</button>}
          {live && <a className="btn btn-secondary" href={waShare} target="_blank" rel="noopener noreferrer">Share on WhatsApp</a>}
        </div>
        <p className="small"><strong>Download QR code</strong></p>
        <div className="qr-dl-grid">
          <button type="button" className="btn-link" onClick={() => dl("png", "card", "print")}>Print card · PNG (high-res)</button>
          <button type="button" className="btn-link" onClick={() => dl("svg", "card", "digital")}>Print card · SVG (vector)</button>
          <button type="button" className="btn-link" onClick={() => dl("png", "plain", "digital")}>Plain QR · PNG (digital)</button>
          <button type="button" className="btn-link" onClick={() => dl("svg", "plain", "digital")}>Plain QR · SVG</button>
        </div>
        <p className="muted small">
          The QR always opens {url.replace("https://", "")} — it keeps working when you update your items. Print at least
          3 × 3 cm and test-scan once before printing in bulk.
        </p>
        <TableQrManager store={store} />
      </div>
    </div>
  );
}
