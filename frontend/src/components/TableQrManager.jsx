import React, { useCallback, useEffect, useState } from "react";
import client, { errorMessage } from "../api/client";
import { downloadFile } from "../api/stores";

const fileSafe = (s) => s.replace(/[^A-Za-z0-9]+/g, "_");

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(blob);
  });
}

/** Sitting-area / table QR codes: add, rename, delete, download and print several at once. */
export default function TableQrManager({ store }) {
  const base = `/qr/stores/${store.id}/tables`;
  const [tables, setTables] = useState([]);
  const [newNo, setNewNo] = useState("");
  const [editId, setEditId] = useState(null);
  const [editNo, setEditNo] = useState("");
  const [selected, setSelected] = useState(() => new Set());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    client.get(base).then(({ data }) => setTables(data)).catch((e) => setError(errorMessage(e, "Could not load tables.")));
  }, [base]);
  useEffect(load, [load]);

  async function run(fn) {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e, "Something went wrong. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  const add = (e) => {
    e.preventDefault();
    if (!newNo.trim()) return;
    run(async () => {
      const { data } = await client.post(base, { table_no: newNo });
      setTables((t) => [...t, data]);
      setNewNo("");
    });
  };

  const saveEdit = (e) => {
    e.preventDefault();
    run(async () => {
      const { data } = await client.patch(`${base}/${editId}`, { table_no: editNo });
      setTables((t) => t.map((x) => (x.id === data.id ? data : x)));
      setEditId(null);
    });
  };

  const remove = (t) => {
    if (!window.confirm(`Delete the QR code for table ${t.table_no}? Printed copies will still open the store, but without the table number.`)) return;
    run(async () => {
      await client.delete(`${base}/${t.id}`);
      setTables((list) => list.filter((x) => x.id !== t.id));
      setSelected((s) => {
        const n = new Set(s);
        n.delete(t.id);
        return n;
      });
    });
  };

  const toggle = (id) =>
    setSelected((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  const allSelected = tables.length > 0 && selected.size === tables.length;

  const download = (t) =>
    run(() => downloadFile(`/qr/stores/${store.id}/qr?format=png&layout=card&size=print&table_id=${t.id}`,
      `${store.slug}-table-${fileSafe(t.table_no)}-qr.png`));

  /** Opens a print sheet with the chosen cards (two per A4 page). */
  const printSelected = () =>
    run(async () => {
      const chosen = tables.filter((t) => selected.has(t.id));
      if (!chosen.length) return;
      const win = window.open("", "_blank");
      if (!win) throw new Error("Allow pop-ups to print.");
      const cards = [];
      try {
        for (const t of chosen) {
          const res = await client.get(`/qr/stores/${store.id}/qr`, {
            params: { format: "png", layout: "card", size: "digital", table_id: t.id }, responseType: "blob",
          });
          cards.push({ no: t.table_no, src: await blobToDataUrl(res.data) });
        }
      } catch (e) {
        win.close();
        throw e;
      }
      const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
      win.document.write(
        `<!doctype html><title>${esc(store.name || "Table QR codes")}</title><style>
          @page{size:A4;margin:10mm}body{margin:0;font-family:sans-serif}
          .sheet{display:grid;grid-template-columns:1fr 1fr;gap:8mm}
          .card{break-inside:avoid;text-align:center}.card img{width:100%;display:block}
        </style><div class="sheet">${cards.map((c) => `<div class="card"><img src="${c.src}" alt="Table ${esc(c.no)}"></div>`).join("")}</div>`
      );
      win.document.close();
      const imgs = Array.from(win.document.images);
      await Promise.all(imgs.map((i) => (i.complete ? null : new Promise((r) => { i.onload = i.onerror = r; }))));
      win.focus();
      win.print();
    });

  return (
    <section className="qr-tables" aria-label="Table QR codes">
      <p className="small"><strong>Sitting area / table QR codes</strong></p>
      <p className="muted small">
        Make one QR per table. When a customer scans it and sends an enquiry on WhatsApp, the table number is included in the message.
      </p>
      <form className="qr-tables-add" onSubmit={add}>
        <input type="text" value={newNo} maxLength={30} placeholder="Table no. (e.g. 5 or Patio 2)"
          aria-label="Table number" onChange={(e) => setNewNo(e.target.value)} />
        <button type="submit" className="btn btn-secondary" disabled={busy || !newNo.trim()}>Add table</button>
      </form>
      {error && <p className="small" role="alert" style={{ color: "var(--danger, #c0392b)" }}>{error}</p>}
      {tables.length > 0 && (
        <>
          <div className="qr-inline-actions">
            <label className="small">
              <input type="checkbox" checked={allSelected}
                onChange={() => setSelected(allSelected ? new Set() : new Set(tables.map((t) => t.id)))} /> Select all
            </label>
            <button type="button" className="btn btn-secondary" disabled={busy || !selected.size} onClick={printSelected}>
              Print selected ({selected.size})
            </button>
          </div>
          <ul className="qr-tables-list">
            {tables.map((t) => (
              <li key={t.id}>
                <input type="checkbox" checked={selected.has(t.id)} onChange={() => toggle(t.id)} aria-label={`Select table ${t.table_no}`} />
                {editId === t.id ? (
                  <form className="qr-tables-add" onSubmit={saveEdit}>
                    <input type="text" value={editNo} maxLength={30} autoFocus aria-label="Table number" onChange={(e) => setEditNo(e.target.value)} />
                    <button type="submit" className="btn-link" disabled={busy || !editNo.trim()}>Save</button>
                    <button type="button" className="btn-link" onClick={() => setEditId(null)}>Cancel</button>
                  </form>
                ) : (
                  <>
                    <span className="qr-tables-name">Table {t.table_no}</span>
                    <button type="button" className="btn-link" onClick={() => { setEditId(t.id); setEditNo(t.table_no); }}>Edit</button>
                    <button type="button" className="btn-link" onClick={() => download(t)}>Download</button>
                    <button type="button" className="btn-link" onClick={() => remove(t)}>Delete</button>
                  </>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
