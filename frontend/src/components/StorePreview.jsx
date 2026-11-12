import React, { useEffect, useState } from "react";
import { previewUrl } from "../api/stores";

/**
 * Live preview of the real storefront render (same templates as the
 * published site), sandboxed in an iframe, at phone or desktop width.
 */
export default function StorePreview({ storeId, template, refreshKey, defaultDevice = "mobile", title = "Store preview" }) {
  const [src, setSrc] = useState(null);
  const [device, setDevice] = useState(defaultDevice);
  const [error, setError] = useState("");

  useEffect(() => {
    let url = null;
    let cancelled = false;
    setError("");
    previewUrl(storeId, template)
      .then((u) => {
        url = u;
        if (!cancelled) setSrc(u);
      })
      .catch(() => !cancelled && setError("Preview unavailable right now."));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [storeId, template, refreshKey]);

  return (
    <div className="qr-preview">
      <div className="qr-seg" role="group" aria-label="Preview size">
        <button type="button" aria-pressed={device === "mobile"} onClick={() => setDevice("mobile")}>📱 Mobile</button>
        <button type="button" aria-pressed={device === "desktop"} onClick={() => setDevice("desktop")}>🖥️ Desktop</button>
      </div>
      <div className={`qr-device qr-device-${device}`}>
        {error ? (
          <p className="muted small qr-preview-msg">{error}</p>
        ) : src ? (
          // allow-scripts only (no same-origin): the preview can run its cart JS but can't touch the app.
          <iframe title={title} src={src} sandbox="allow-scripts allow-popups" loading="lazy" />
        ) : (
          <p className="muted small qr-preview-msg"><span className="qr-spinner" aria-hidden="true" /> Building preview…</p>
        )}
      </div>
    </div>
  );
}
