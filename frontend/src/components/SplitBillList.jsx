import React, { useCallback, useEffect, useState } from "react";
import client, { errorMessage } from "../api/client";

const STATUS = {
  payment_confirmed: ["Payment confirmed", "qr-sb-chip qr-sb-ok"],
  notification_failed: ["Notification failed", "qr-sb-chip qr-sb-bad"],
  pending: ["Pending", "qr-sb-chip"],
};

const rupees = (paise) => `₹${(paise / 100).toLocaleString("en-IN", { minimumFractionDigits: paise % 100 ? 2 : 0, maximumFractionDigits: 2 })}`;

/** Recent split bills for the merchant; payment is marked confirmed only here, by the merchant. */
export default function SplitBillList({ storeId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    return client.get(`/qr/stores/${storeId}/split-bills`, { params: { limit: 25 } })
      .then(({ data: d }) => { setData(d); setError(""); })
      .catch((err) => setError(errorMessage(err, "Could not load split bills.")));
  }, [storeId]);
  useEffect(() => { load(); }, [load]);

  async function mark(bill, p, status) {
    setBusy(p.id);
    try {
      const { data: updated } = await client.put(`/qr/stores/${storeId}/split-bills/${bill.id}/participants/${p.id}/payment`, { status });
      setData((d) => ({ ...d, bills: d.bills.map((b) => (b.id === updated.id ? updated : b)) }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="card" aria-labelledby="sbl-title">
      <div className="qr-sb-head">
        <h2 id="sbl-title">Recent split bills</h2>
        <button type="button" className="btn btn-secondary" onClick={load}>Refresh</button>
      </div>
      <p className="muted small">
        A WhatsApp message or QR scan doesn't prove payment. Mark someone as paid once you've seen the money arrive in your account.
      </p>
      {error && <p className="error-text" role="alert">{error}</p>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && data.bills.length === 0 && (
        <div className="qr-empty"><p className="qr-big" aria-hidden="true">🧾</p><p className="muted">No split bills yet. They'll show up here when customers use Split Bill.</p></div>
      )}
      {data && data.bills.length > 0 && (
        <ul className="qr-sb-list">
          {data.bills.map((b) => (
            <li key={b.id} className="qr-sb-item">
              <button type="button" className="qr-sb-row" aria-expanded={open === b.id} onClick={() => setOpen(open === b.id ? null : b.id)}>
                <span>
                  <strong>{rupees(b.total_paise)}</strong> · {b.participant_count} people{b.table_no ? ` · Table ${b.table_no}` : ""}
                  <span className="muted small qr-sb-block">{b.code} · {new Date(b.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</span>
                </span>
                <span className="small">{b.paid_count}/{b.participant_count} paid<span className="muted qr-sb-block">{rupees(b.outstanding_paise)} due</span></span>
              </button>
              {open === b.id && (
                <table className="qr-sb-table">
                  <thead><tr><th scope="col">Participant</th><th scope="col">Share</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Action</span></th></tr></thead>
                  <tbody>
                    {b.participants.map((p, i) => {
                      const [label, cls] = STATUS[p.status] || STATUS.pending;
                      return (
                        <tr key={p.id}>
                          <td>{p.name || `Person ${i + 1}`}<span className="muted small qr-sb-block">{p.phone_masked}</span></td>
                          <td>{rupees(p.share_paise)}</td>
                          <td><span className={cls}>{label}</span>
                            {p.notification_error && <span className="muted small qr-sb-block">{p.notification_error}</span>}</td>
                          <td>
                            {p.payment_status === "confirmed"
                              ? <button type="button" className="btn-link" disabled={busy === p.id} onClick={() => mark(b, p, "pending")}>Undo</button>
                              : <button type="button" className="btn btn-secondary" disabled={busy === p.id} onClick={() => mark(b, p, "confirmed")}>Mark paid</button>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </li>
          ))}
        </ul>
      )}
      {data && data.total > data.bills.length && <p className="muted small">Showing the latest {data.bills.length} of {data.total}.</p>}
    </section>
  );
}
