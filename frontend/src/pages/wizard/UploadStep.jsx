import React, { useEffect, useRef, useState } from "react";
import client, { errorMessage } from "../../api/client";
import { StepNav } from "./Wizard";

const ACCEPT = "image/jpeg,image/png,image/webp";
const ACCEPT_EXT = /\.(jpe?g|png|webp)$/i;

export default function UploadStep({ store, setStore, meta, onNext, onBack }) {
  const [sources, setSources] = useState(store.sources);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [warnings, setWarnings] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);
  const cameraRef = useRef(null);
  const maxBytes = meta.max_upload_mb * 1024 * 1024;
  const job = store.job;
  const analysing = job && ["queued", "running"].includes(job.status);

  useEffect(() => setSources(store.sources), [store.sources]);

  async function upload(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const problems = [];
    const ok = files.filter((f) => {
      if (!ACCEPT.split(",").includes(f.type) && !ACCEPT_EXT.test(f.name)) {
        problems.push(`${f.name}: please use a JPG, PNG or WEBP photo.`);
        return false;
      }
      if (f.size > maxBytes) {
        problems.push(`${f.name}: photos must be ${meta.max_upload_mb} MB or smaller.`);
        return false;
      }
      return true;
    });
    if (sources.length + ok.length > meta.max_source_images) {
      problems.push(`You can upload up to ${meta.max_source_images} photos.`);
      ok.splice(meta.max_source_images - sources.length);
    }
    setWarnings(problems);
    if (!ok.length) return;
    setUploading(true);
    setError("");
    const form = new FormData();
    ok.forEach((f) => form.append("files", f));
    try {
      const { data } = await client.post(`/qr/stores/${store.id}/sources`, form);
      setSources(data.sources);
      setStore((s) => ({ ...s, sources: data.sources }));
      if (data.errors?.length) setWarnings((w) => [...w, ...data.errors.map((e) => `${e.filename}: ${e.message}`)]);
    } catch (err) {
      setError(errorMessage(err, "Upload failed. Please try again."));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
      if (cameraRef.current) cameraRef.current.value = "";
    }
  }

  async function remove(id) {
    try {
      const { data } = await client.delete(`/qr/stores/${store.id}/sources/${id}`);
      setSources(data.sources);
      setStore((s) => ({ ...s, sources: data.sources }));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function move(id, delta) {
    const ids = sources.map((s) => s.id);
    const i = ids.indexOf(id);
    const j = i + delta;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    try {
      const { data } = await client.put(`/qr/stores/${store.id}/sources/order`, { media_ids: ids });
      setSources(data.sources);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function analyse() {
    setBusy(true);
    setError("");
    try {
      const { data } = await client.post(`/qr/stores/${store.id}/analysis`);
      setStore((s) => ({ ...s, job: data }));
      onNext();
    } catch (err) {
      if (err.response?.status === 409) onNext();
      else setError(errorMessage(err, "Couldn't start the analysis. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  const analysedIds = new Set((job?.pages || []).map((p) => p.media_id));
  const changedSinceAnalysis = job && (sources.length !== analysedIds.size || sources.some((s) => !analysedIds.has(s.id)));

  return (
    <section className="card" aria-labelledby="upload-title">
      <h1 id="upload-title">Upload your menu or product list</h1>
      <p className="muted">
        Upload a photo of your menu, catalogue, price list, wedding collection or product sheet. Our AI reads the items and
        prices and suggests your store type — you'll review everything before anything goes live.
      </p>

      <div
        className={"qr-drop" + (dragging ? " is-dragging" : "")}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          upload(e.dataTransfer.files);
        }}
      >
        <div className="qr-drop-icon" aria-hidden="true">📷</div>
        <p><strong>Drag photos here</strong> <span className="qr-hide-sm">or</span></p>
        <div className="qr-drop-actions">
          <button type="button" className="btn btn-primary" onClick={() => cameraRef.current?.click()} disabled={uploading}>
            Take a photo
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => fileRef.current?.click()} disabled={uploading}>
            Choose files
          </button>
        </div>
        <input ref={cameraRef} type="file" accept={ACCEPT} capture="environment" hidden onChange={(e) => upload(e.target.files)} />
        <input ref={fileRef} type="file" accept={ACCEPT} multiple hidden onChange={(e) => upload(e.target.files)} />
        <p className="muted small">
          JPG, PNG or WEBP · up to {meta.max_upload_mb} MB each · up to {meta.max_source_images} pages for longer menus
        </p>
      </div>

      <ul className="qr-tips muted small">
        <li>Lay the menu flat in good light and fill the frame.</li>
        <li>For long menus, take one photo per page — keep each page sharp and readable.</li>
      </ul>

      {uploading && <p className="muted" role="status"><span className="qr-spinner" aria-hidden="true" /> Uploading…</p>}
      {warnings.map((w) => <p key={w} className="error-text small">{w}</p>)}
      {error && <p className="error-text" role="alert">{error}</p>}

      {sources.length > 0 && (
        <ol className="qr-thumbs" aria-label="Uploaded pages">
          {sources.map((s, i) => (
            <li key={s.id} className="qr-thumb">
              <img src={s.thumb_url} alt={`Page ${i + 1}`} />
              <span className="qr-thumb-num">Page {i + 1}</span>
              <div className="qr-thumb-actions">
                <button type="button" className="icon-btn" onClick={() => move(s.id, -1)} disabled={i === 0} aria-label={`Move page ${i + 1} earlier`}>↑</button>
                <button type="button" className="icon-btn" onClick={() => move(s.id, 1)} disabled={i === sources.length - 1} aria-label={`Move page ${i + 1} later`}>↓</button>
                <button type="button" className="icon-btn" onClick={() => remove(s.id)} aria-label={`Remove page ${i + 1}`}>✕</button>
              </div>
            </li>
          ))}
        </ol>
      )}

      {job && !changedSinceAnalysis && !analysing && (
        <p className="muted small">These photos were already analysed. Continue, or add/replace photos to analyse again.</p>
      )}

      <StepNav
        onBack={onBack}
        onNext={job && !changedSinceAnalysis ? onNext : analyse}
        nextLabel={analysing ? "View progress" : job && !changedSinceAnalysis ? "Next" : "Analyse with AI"}
        nextDisabled={!sources.length || uploading}
        busy={busy}
        hint={!sources.length ? "Add at least one photo" : null}
      />
      <p className="muted small qr-skip">
        No menu photo?{" "}
        <button type="button" className="btn-link" onClick={onNext}>Skip and add items yourself</button>
      </p>
    </section>
  );
}
