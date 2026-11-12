import { useCallback, useEffect, useState } from "react";
import client, { errorMessage } from "./client";

/** Loads one owned store and exposes reload / optimistic replace. */
export function useStore(storeId) {
  const [store, setStore] = useState(null);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    return client
      .get(`/qr/stores/${storeId}`)
      .then(({ data }) => {
        setStore(data);
        setError("");
        return data;
      })
      .catch((err) => setError(errorMessage(err, "Could not load your store.")));
  }, [storeId]);
  useEffect(() => {
    reload();
  }, [reload]);
  return { store, setStore, error, reload };
}

let metaCache = null;
export function useMeta() {
  const [meta, setMeta] = useState(metaCache);
  useEffect(() => {
    if (metaCache) return;
    client.get("/qr/meta").then(({ data }) => {
      metaCache = data;
      setMeta(data);
    });
  }, []);
  return meta;
}

export async function patchStore(storeId, body) {
  const { data } = await client.patch(`/qr/stores/${storeId}`, body);
  return data;
}

/** Field-level error message from a {field, message} or validation-list detail. */
export function fieldErrors(err) {
  const detail = err?.response?.data?.detail;
  const out = {};
  if (detail && typeof detail === "object") {
    if (detail.field) out[detail.field] = detail.message;
    (detail.errors || []).forEach((e) => {
      if (e.field) out[e.field] = e.message;
    });
  }
  return out;
}

/** Downloads an authenticated binary (QR codes) as a file. */
export async function downloadFile(url, filename) {
  const res = await client.get(url, { responseType: "blob" });
  const href = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

/** Fetches the authenticated HTML preview and returns an object URL for an iframe. */
export async function previewUrl(storeId, template) {
  const res = await client.get(`/qr/stores/${storeId}/preview`, {
    params: template ? { template } : {},
    responseType: "text",
  });
  // Blob documents have an opaque base URL, so give the preview an absolute
  // base for its signed /api/qr/media/... image URLs.
  const html = String(res.data).replace("<head>", `<head><base href="${window.location.origin}/">`);
  return URL.createObjectURL(new Blob([html], { type: "text/html" }));
}

export function formatINR(value, currency = "INR") {
  if (value == null || value === "") return null;
  const n = Number(value);
  if (Number.isNaN(n)) return null;
  try {
    return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: n % 1 === 0 ? 0 : 2,
    }).format(n);
  } catch {
    return `${currency} ${n}`;
  }
}
