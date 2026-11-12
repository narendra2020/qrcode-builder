import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import client, { errorMessage } from "../api/client";
import { formatINR } from "../api/stores";

const REASONS = {
  name_unclear: "Name was hard to read",
  price_unclear: "Price couldn't be read exactly",
  price_low_confidence: "Price may be misread",
  variant_price_unclear: "An option price couldn't be read",
  flagged_by_ai: "AI marked this as uncertain",
};

let seq = 0;
const localKey = () => `new-${Date.now().toString(36)}-${seq++}`;

function toDraft(cat) {
  return {
    version: cat.version,
    currency: cat.currency,
    categories: cat.categories.map((c) => ({ key: c.id, id: c.id, name: c.name })),
    items: cat.items.map((i) => ({
      key: i.id,
      id: i.id,
      category: i.category_id,
      name: i.name,
      description: i.description || "",
      price: i.price ?? "",
      price_text: i.price_text || "",
      variants: i.variants || [],
      labels: i.labels || [],
      available: i.available,
      image: i.image,
      needs_review: i.needs_review,
      review_reasons: i.review_reasons || [],
      source: i.source,
    })),
  };
}

function toPayload(draft) {
  return {
    base_version: draft.version,
    categories: draft.categories.map((c) => ({ ref: c.key, id: c.id || null, name: c.name })),
    items: draft.items.map((i) => ({
      id: i.id || null,
      category_ref: i.category || null,
      name: i.name,
      description: i.description || null,
      price: i.price === "" ? null : String(i.price),
      price_text: i.price === "" ? i.price_text || null : null,
      variants: i.variants.filter((v) => v.name),
      labels: i.labels,
      available: i.available,
      image_media_id: i.image?.id || null,
      needs_review: i.needs_review,
    })),
  };
}

/**
 * Catalogue review + editing. All changes stay local until one explicit
 * "Save" — a single save is one catalogue update for quota purposes, no
 * matter how many items changed. Unsaved drafts survive reloads and quota
 * blocks via localStorage.
 */
export default function CatalogueEditor({ storeId, meta, category, isLive, onSaved, onUsage }) {
  const draftKey = `qr-draft:${storeId}`;
  const [server, setServer] = useState(null);
  const [draft, setDraft] = useState(null);
  const [usage, setUsage] = useState(null);
  const [extracted, setExtracted] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [rowErrors, setRowErrors] = useState({});
  const [notice, setNotice] = useState("");
  const [quota, setQuota] = useState(null);
  const [conflict, setConflict] = useState(false);
  const [filter, setFilter] = useState("all");
  const [restored, setRestored] = useState(false);
  const loaded = useRef(false);

  const load = useCallback(async ({ keepDraft = true } = {}) => {
    const { data } = await client.get(`/qr/stores/${storeId}/catalogue`);
    setServer(data);
    setUsage(data.usage);
    onUsage?.(data.usage);
    setExtracted(data.extracted || []);
    let saved = null;
    try {
      saved = keepDraft ? JSON.parse(localStorage.getItem(draftKey) || "null") : null;
    } catch {
      saved = null;
    }
    if (saved && saved.version === data.version) {
      setDraft(saved);
      setRestored(true);
    } else {
      setDraft(toDraft(data));
      if (!keepDraft) localStorage.removeItem(draftKey);
    }
  }, [storeId, draftKey, onUsage]);

  useEffect(() => {
    if (loaded.current) return;
    loaded.current = true;
    load().catch((err) => setError(errorMessage(err, "Could not load your catalogue.")));
  }, [load]);

  const dirty = useMemo(() => {
    if (!server || !draft) return false;
    return JSON.stringify(toPayload(draft)) !== JSON.stringify(toPayload(toDraft(server)));
  }, [server, draft]);

  useEffect(() => {
    if (!draft) return;
    if (dirty) localStorage.setItem(draftKey, JSON.stringify(draft));
    else localStorage.removeItem(draftKey);
  }, [draft, dirty, draftKey]);

  useEffect(() => {
    const warn = (e) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (error && !draft) return <p className="error-text" role="alert">{error}</p>;
  if (!draft) return <p className="muted"><span className="qr-spinner" aria-hidden="true" /> Loading catalogue…</p>;

  const update = (fn) => setDraft((d) => fn(structuredClone(d)));
  const setItem = (key, patch) =>
    update((d) => {
      const it = d.items.find((i) => i.key === key);
      Object.assign(it, patch);
      return d;
    });

  function addCategory() {
    const name = window.prompt(`New ${category?.catalogue_noun === "Menu" ? "menu section" : "category"} name`);
    if (!name?.trim()) return;
    update((d) => {
      d.categories.push({ key: localKey(), id: null, name: name.trim().slice(0, 80) });
      return d;
    });
  }

  function renameCategory(key) {
    const c = draft.categories.find((x) => x.key === key);
    const name = window.prompt("Rename category", c.name);
    if (!name?.trim()) return;
    update((d) => {
      d.categories.find((x) => x.key === key).name = name.trim().slice(0, 80);
      return d;
    });
  }

  function deleteCategory(key) {
    const count = draft.items.filter((i) => i.category === key).length;
    if (count && !window.confirm(`Delete this category? Its ${count} item(s) will move to "Other".`)) return;
    update((d) => {
      d.categories = d.categories.filter((c) => c.key !== key);
      d.items.forEach((i) => {
        if (i.category === key) i.category = null;
      });
      return d;
    });
  }

  function moveCategory(key, delta) {
    update((d) => {
      const i = d.categories.findIndex((c) => c.key === key);
      const j = i + delta;
      if (j >= 0 && j < d.categories.length) [d.categories[i], d.categories[j]] = [d.categories[j], d.categories[i]];
      return d;
    });
  }

  function addItem(catKey, from = null) {
    update((d) => {
      d.items.push({
        key: localKey(), id: null, category: catKey, name: from?.name || "", description: from?.description || "",
        price: from?.price ?? "", price_text: from?.price_text || "", variants: from?.variants || [], labels: from?.labels || [],
        available: true, image: null, needs_review: false, review_reasons: [], source: "manual",
      });
      return d;
    });
  }

  function addExtracted() {
    update((d) => {
      extracted.forEach((x) => {
        let cat = d.categories.find((c) => c.name.toLowerCase() === (x.section || "Other").toLowerCase());
        if (!cat) {
          cat = { key: localKey(), id: null, name: (x.section || "Other").slice(0, 80) };
          d.categories.push(cat);
        }
        d.items.push({
          key: localKey(), id: null, category: cat.key, name: x.name, description: x.description || "",
          price: x.price ?? "", price_text: x.price_text || "", variants: x.variants || [], labels: x.labels || [],
          available: true, image: null, needs_review: false, review_reasons: [], source: "manual",
        });
      });
      return d;
    });
    setExtracted([]);
    setNotice("Extracted items added below — review them, then save to publish.");
  }

  function deleteItem(key) {
    update((d) => {
      d.items = d.items.filter((i) => i.key !== key);
      return d;
    });
  }

  function moveItem(key, delta) {
    update((d) => {
      const item = d.items.find((i) => i.key === key);
      const siblings = d.items.filter((i) => i.category === item.category);
      const pos = siblings.indexOf(item);
      const swap = siblings[pos + delta];
      if (!swap) return d;
      const a = d.items.indexOf(item);
      const b = d.items.indexOf(swap);
      [d.items[a], d.items[b]] = [d.items[b], d.items[a]];
      return d;
    });
  }

  async function uploadImage(key, file) {
    if (!file) return;
    if (file.size > meta.max_upload_mb * 1024 * 1024) {
      setRowErrors((e) => ({ ...e, [key]: `Image must be ${meta.max_upload_mb} MB or smaller.` }));
      return;
    }
    const form = new FormData();
    form.append("kind", "item_image");
    form.append("file", file);
    try {
      const { data } = await client.post(`/qr/stores/${storeId}/media`, form);
      setItem(key, { image: data });
      setRowErrors((e) => ({ ...e, [key]: undefined }));
    } catch (err) {
      setRowErrors((e) => ({ ...e, [key]: errorMessage(err, "Upload failed.") }));
    }
  }

  async function save() {
    setBusy(true);
    setError("");
    setNotice("");
    setQuota(null);
    setRowErrors({});
    try {
      const { data } = await client.put(`/qr/stores/${storeId}/catalogue`, toPayload(draft));
      setServer({ ...data.catalogue, usage: data.usage });
      setDraft(toDraft(data.catalogue));
      setUsage(data.usage);
      onUsage?.(data.usage);
      localStorage.removeItem(draftKey);
      setRestored(false);
      setNotice(
        !data.changed ? "No changes to save." : data.counted
          ? `Saved and published. ${data.usage.unlimited ? "" : `${data.usage.remaining} update(s) left this month.`}`
          : isLive ? "Saved." : "Saved."
      );
      onSaved?.(data);
    } catch (err) {
      const status = err.response?.status;
      const detail = err.response?.data?.detail;
      if (status === 402 && detail?.code === "quota_exceeded") {
        setQuota(detail);
        setUsage(detail.usage);
      } else if (status === 409) {
        setConflict(true);
      } else if (status === 422 && detail?.errors) {
        const map = {};
        detail.errors.forEach((e) => {
          const m = /^items\[(\d+)\]/.exec(e.where || "");
          if (m) map[draft.items[Number(m[1])]?.key] = e.message;
        });
        setRowErrors(map);
        setError(detail.message);
      } else setError(errorMessage(err, "Couldn't save. Your changes are kept — please try again."));
    } finally {
      setBusy(false);
    }
  }

  async function discardAndReload() {
    setConflict(false);
    await load({ keepDraft: false });
  }

  const reviewCount = draft.items.filter((i) => i.needs_review).length;
  const groups = [
    ...draft.categories.map((c) => ({ ...c, items: draft.items.filter((i) => i.category === c.key) })),
    { key: null, name: "Other", items: draft.items.filter((i) => !i.category || !draft.categories.some((c) => c.key === i.category)) },
  ].filter((g) => g.key !== null || g.items.length);
  const visible = (i) => filter === "all" || (filter === "review" && i.needs_review) || (filter === "unavailable" && !i.available);
  const quotaBlocked = isLive && usage && !usage.unlimited && usage.remaining === 0;

  return (
    <div className="qr-editor">
      {isLive && usage && <UsageBar usage={usage} storeId={storeId} />}
      {restored && dirty && (
        <p className="qr-banner" role="status">
          We restored your unsaved changes.{" "}
          <button type="button" className="btn-link" onClick={discardAndReload}>Discard them</button>
        </p>
      )}
      {reviewCount > 0 && (
        <div className="qr-job qr-job-warn" role="note">
          <strong>{reviewCount} item(s) need your check.</strong> The AI wasn't sure about these names or prices. Fix
          them or tap <em>Looks right</em> — your store can't be published until they're reviewed.
          <button type="button" className="btn-link" onClick={() => setFilter("review")}>Show them</button>
        </div>
      )}
      {extracted.length > 0 && (
        <div className="qr-banner">
          {extracted.length} item(s) were extracted from your latest photos.{" "}
          <button type="button" className="btn-link" onClick={addExtracted}>Add them to the editor</button>
        </div>
      )}

      <div className="qr-editor-toolbar">
        <div className="qr-seg" role="group" aria-label="Filter items">
          <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All ({draft.items.length})</button>
          <button type="button" aria-pressed={filter === "review"} onClick={() => setFilter("review")}>Needs review ({reviewCount})</button>
          <button type="button" aria-pressed={filter === "unavailable"} onClick={() => setFilter("unavailable")}>Unavailable</button>
        </div>
        <button type="button" className="btn btn-secondary" onClick={addCategory}>+ Category</button>
      </div>

      {draft.items.length === 0 && (
        <div className="qr-empty">
          <p className="qr-empty-icon" aria-hidden="true">{category?.icon || "🛍️"}</p>
          <p>No items yet. Add your first {category?.item_noun || "item"}.</p>
        </div>
      )}

      {groups.map((g, gi) => (
        <section key={g.key || "other"} className="qr-group" aria-label={g.name}>
          <header className="qr-group-head">
            <h3>{g.name} <span className="muted small">({g.items.length})</span></h3>
            {g.key && (
              <div className="qr-row-actions">
                <button type="button" className="icon-btn" onClick={() => moveCategory(g.key, -1)} disabled={gi === 0} aria-label={`Move ${g.name} up`}>↑</button>
                <button type="button" className="icon-btn" onClick={() => moveCategory(g.key, 1)} disabled={gi >= draft.categories.length - 1} aria-label={`Move ${g.name} down`}>↓</button>
                <button type="button" className="btn-link" onClick={() => renameCategory(g.key)}>Rename</button>
                <button type="button" className="btn-link qr-danger" onClick={() => deleteCategory(g.key)}>Delete</button>
              </div>
            )}
          </header>
          <ul className="qr-items">
            {g.items.filter(visible).map((item, ii) => (
              <ItemRow
                key={item.key}
                item={item}
                index={ii}
                last={ii === g.items.length - 1}
                categories={draft.categories}
                meta={meta}
                category={category}
                currency={draft.currency}
                error={rowErrors[item.key]}
                onChange={(patch) => setItem(item.key, patch)}
                onDelete={() => deleteItem(item.key)}
                onMove={(d) => moveItem(item.key, d)}
                onImage={(f) => uploadImage(item.key, f)}
              />
            ))}
          </ul>
          <button type="button" className="btn-link" onClick={() => addItem(g.key)}>+ Add {category?.item_noun || "item"}</button>
        </section>
      ))}

      {conflict && (
        <div className="qr-job qr-job-error" role="alert">
          <strong>Your catalogue changed elsewhere</strong>
          <p className="small">It was updated in another tab or by a new import. Reload the latest version (your unsaved edits here will be lost).</p>
          <button type="button" className="btn btn-secondary" onClick={discardAndReload}>Reload latest</button>
        </div>
      )}
      {quota && (
        <div className="qr-job qr-job-error" role="alert">
          <strong>Monthly update limit reached</strong>
          <p className="small">{quota.message}</p>
          <p className="small muted">Resets on {new Date(quota.usage.resets_at).toLocaleDateString("en-IN", { day: "numeric", month: "long" })}.</p>
          <Link className="btn btn-primary" to={`/stores/${storeId}/upgrade`}>Upgrade plan</Link>
        </div>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}
      {notice && <p className="success-text" role="status">{notice}</p>}

      <div className="qr-save-bar">
        <span className="muted small">
          {dirty ? "You have unsaved changes." : "All changes saved."}
          {isLive && dirty && !usage?.unlimited && " Saving uses 1 monthly update, however many items you changed."}
        </span>
        <button type="button" className="btn btn-primary" onClick={save} disabled={busy || !dirty || quotaBlocked}>
          {busy ? "Saving…" : isLive ? "Save & publish changes" : "Save catalogue"}
        </button>
      </div>
    </div>
  );
}

function ItemRow({ item, index, last, categories, meta, category, currency, error, onChange, onDelete, onMove, onImage }) {
  const [open, setOpen] = useState(!item.name || item.needs_review);
  const fileRef = useRef(null);
  const id = `it-${item.key}`;
  const priceShown = item.price !== "" ? formatINR(item.price, currency) : item.price_text || "No price";
  const labelOptions = Object.entries(meta.item_labels).filter(
    ([k]) => category?.supports_diet_labels || !["veg", "non_veg", "egg", "jain"].includes(k)
  );

  return (
    <li className={"qr-item" + (item.needs_review ? " needs-review" : "") + (!item.available ? " is-off" : "")}>
      <div className="qr-item-summary">
        <button type="button" className="qr-item-img" onClick={() => fileRef.current?.click()} aria-label={item.image ? `Replace photo of ${item.name}` : `Add photo for ${item.name || "item"}`}>
          {item.image ? <img src={item.image.thumb_url} alt="" /> : <span aria-hidden="true">{category?.icon || "📷"}</span>}
        </button>
        <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(e) => onImage(e.target.files?.[0])} />
        <button type="button" className="qr-item-title" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls={id}>
          <strong>{item.name || <em className="muted">Untitled</em>}</strong>
          <span className="muted small">{priceShown}{!item.available && " · Unavailable"}{item.needs_review && " · ⚠ Needs review"}</span>
        </button>
        <div className="qr-row-actions">
          <button type="button" className="icon-btn" onClick={() => onMove(-1)} disabled={index === 0} aria-label={`Move ${item.name} up`}>↑</button>
          <button type="button" className="icon-btn" onClick={() => onMove(1)} disabled={last} aria-label={`Move ${item.name} down`}>↓</button>
        </div>
      </div>

      {open && (
        <div id={id} className="qr-item-form">
          {item.needs_review && (
            <div className="qr-review-note">
              <span>⚠ {item.review_reasons.map((r) => REASONS[r] || r).join("; ") || "Please check this item"}</span>
              <button type="button" className="btn btn-secondary" onClick={() => onChange({ needs_review: false })}>Looks right</button>
            </div>
          )}
          <div className="qr-form-grid">
            <div className="field-group">
              <label htmlFor={`${id}-name`}>Name<span className="required-mark" aria-hidden="true">*</span></label>
              <input id={`${id}-name`} type="text" value={item.name} maxLength={160} onChange={(e) => onChange({ name: e.target.value })} />
            </div>
            <div className="field-group">
              <label htmlFor={`${id}-cat`}>Category</label>
              <select id={`${id}-cat`} value={item.category || ""} onChange={(e) => onChange({ category: e.target.value || null })}>
                <option value="">Other</option>
                {categories.map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
              </select>
            </div>
            <div className="field-group">
              <label htmlFor={`${id}-price`}>Price ({currency})</label>
              <input id={`${id}-price`} type="text" inputMode="decimal" value={item.price} placeholder="Leave blank if not fixed"
                onChange={(e) => onChange({ price: e.target.value.replace(/[^\d.]/g, "") })} />
              {item.price === "" && item.price_text && <p className="muted small">Printed as: “{item.price_text}”</p>}
            </div>
          </div>
          <div className="field-group">
            <label htmlFor={`${id}-desc`}>Description</label>
            <textarea id={`${id}-desc`} rows={2} maxLength={1000} value={item.description} onChange={(e) => onChange({ description: e.target.value })} />
          </div>

          <fieldset className="field-group">
            <legend className="small"><strong>Options / sizes</strong> <span className="muted">(e.g. Half / Full)</span></legend>
            {item.variants.map((v, vi) => (
              <div key={vi} className="link-row">
                <input type="text" aria-label="Option name" placeholder="Option" value={v.name} maxLength={60}
                  onChange={(e) => onChange({ variants: item.variants.map((x, xi) => (xi === vi ? { ...x, name: e.target.value } : x)) })} />
                <input type="text" inputMode="decimal" aria-label="Option price" placeholder="Price" value={v.price ?? ""}
                  onChange={(e) => onChange({ variants: item.variants.map((x, xi) => (xi === vi ? { ...x, price: e.target.value.replace(/[^\d.]/g, "") || null } : x)) })} />
                <button type="button" className="icon-btn" aria-label="Remove option" onClick={() => onChange({ variants: item.variants.filter((_, xi) => xi !== vi) })}>✕</button>
              </div>
            ))}
            {item.variants.length < 12 && (
              <button type="button" className="btn-link" onClick={() => onChange({ variants: [...item.variants, { name: "", price: null, price_text: null }] })}>+ Add option</button>
            )}
          </fieldset>

          <fieldset className="field-group">
            <legend className="small"><strong>Labels</strong></legend>
            <div className="qr-chip-row">
              {labelOptions.map(([k, label]) => (
                <label key={k} className={"qr-chip" + (item.labels.includes(k) ? " is-on" : "")}>
                  <input type="checkbox" checked={item.labels.includes(k)}
                    onChange={(e) => onChange({ labels: e.target.checked ? [...item.labels, k] : item.labels.filter((x) => x !== k) })} />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>

          <div className="qr-item-foot">
            <label className="choice-row">
              <input type="checkbox" checked={item.available} onChange={(e) => onChange({ available: e.target.checked })} /> Available
            </label>
            {item.image && <button type="button" className="btn-link" onClick={() => onChange({ image: null })}>Remove photo</button>}
            <button type="button" className="btn-link qr-danger" onClick={onDelete}>Delete item</button>
          </div>
          {!item.image && (
            <p className="muted small">No photo? Customers see a simple {category?.label?.split(",")[0].toLowerCase() || "category"} icon — never a stock photo pretending to be your product.</p>
          )}
        </div>
      )}
      {error && <p className="error-text small" role="alert">{error}</p>}
    </li>
  );
}

export function UsageBar({ usage, storeId }) {
  if (!usage) return null;
  if (usage.unlimited) {
    return <p className="qr-usage"><strong>Catalogue updates:</strong> unlimited on {usage.plan.name}</p>;
  }
  const pct = Math.min(100, (usage.used / usage.limit) * 100);
  return (
    <div className="qr-usage">
      <div className="qr-usage-text">
        <strong>Catalogue updates: {usage.used} of {usage.limit} used</strong>
        <span className="muted small">
          {usage.remaining} update{usage.remaining === 1 ? "" : "s"} remaining this month · resets{" "}
          {new Date(usage.resets_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} (IST)
        </span>
      </div>
      <div className="step-progress-bar" aria-hidden="true">
        <div className="step-progress-fill" style={{ width: `${pct}%`, background: usage.remaining === 0 ? "var(--error)" : undefined }} />
      </div>
      {usage.remaining <= 1 && storeId && <Link to={`/stores/${storeId}/upgrade`} className="btn-link">Need more updates? Upgrade</Link>}
    </div>
  );
}
