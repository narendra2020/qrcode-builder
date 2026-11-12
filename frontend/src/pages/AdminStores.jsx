import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import client, { errorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";

export default function AdminStores() {
  const { startGhost } = useAuth();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState(null);
  const [plans, setPlans] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [diag, setDiag] = useState(null);
  const [error, setError] = useState("");

  const search = () =>
    client.get("/qr/admin/stores", { params: { q: q || undefined } })
      .then(({ data }) => setRows(data.stores))
      .catch((err) => setError(errorMessage(err)));

  useEffect(() => {
    search();
    client.get("/qr/admin/plans").then(({ data }) => setPlans(data));
    client.get("/qr/admin/jobs").then(({ data }) => setJobs(data));
    client.get("/qr/admin/diagnostics").then(({ data }) => setDiag(data));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function open(id) {
    try {
      const { data } = await client.get(`/qr/admin/stores/${id}`);
      setSelected(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function act(path, body) {
    setError("");
    try {
      await client.post(path, body);
      if (selected) await open(selected.id);
      search();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function ghostLogin(storeId, ownerName) {
    if (!window.confirm(`Manage this store as ${ownerName}? Your actions are logged under your admin account, and the session ends after an hour.`)) return;
    setError("");
    try {
      const id = await startGhost(storeId);
      navigate(`/stores/${id}`);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function savePlan(p) {
    const raw = window.prompt(`Monthly catalogue updates for ${p.name} (blank = unlimited)`, p.monthly_catalogue_updates ?? "");
    if (raw === null) return;
    const body = raw.trim() === "" ? { unlimited: true } : { monthly_catalogue_updates: Number(raw) };
    try {
      await client.put(`/qr/admin/plans/${p.code}`, body);
      const { data } = await client.get("/qr/admin/plans");
      setPlans(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div>
      <section className="card">
        <h1>Store admin</h1>
        {diag && (
          <p className="muted small">
            AI: {diag.ai.configured ? `${diag.ai.provider} / ${diag.ai.model}` : `not configured — ${diag.ai.message}`} ·
            Stores: {Object.entries(diag.stores).map(([k, v]) => `${k} ${v}`).join(", ") || "none"} ·
            Quota period {diag.current_period} ({diag.quota_timezone})
          </p>
        )}
        <form onSubmit={(e) => { e.preventDefault(); search(); }} className="qr-inline-actions">
          <label htmlFor="adm-q" className="sr-only">Search</label>
          <input id="adm-q" type="text" placeholder="Store, address or owner name" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="btn btn-primary" type="submit">Search</button>
        </form>
        {error && <p className="error-text" role="alert">{error}</p>}
        <table className="admin-table">
          <thead><tr><th>Store</th><th>Owner</th><th>Status</th><th>Plan</th><th>Updates (month)</th><th /></tr></thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id}>
                <td>{s.name || "—"}<br /><span className="muted small">{s.slug || "no address"}</span></td>
                <td>{s.owner.name}</td>
                <td>{s.status}</td>
                <td>{s.plan}</td>
                <td>{s.used_this_month}</td>
                <td><button className="btn-link" onClick={() => open(s.id)}>Details</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {selected && (
        <section className="card">
          <h2>{selected.name} <span className="muted small">{selected.public_url}</span></h2>
          <p className="small">
            Status: <strong>{selected.status}</strong> · Items: {selected.item_count} · Plan: {selected.usage.plan.name} ·
            Updates: {selected.usage.used}/{selected.usage.unlimited ? "∞" : selected.usage.limit}
          </p>
          <div className="qr-inline-actions">
            {selected.status === "suspended" ? (
              <button className="btn btn-secondary" onClick={() => act(`/qr/admin/stores/${selected.id}/restore`)}>Restore</button>
            ) : (
              <button className="btn btn-secondary" onClick={() => {
                const reason = window.prompt("Reason for suspending (shown to the owner)");
                if (reason && reason.trim().length >= 3) act(`/qr/admin/stores/${selected.id}/suspend`, { reason });
              }}>Suspend</button>
            )}
            <button className="btn btn-primary" onClick={() => ghostLogin(selected.id, selected.owner.name)}>
              Manage as owner (ghost login)
            </button>
            <button className="btn btn-secondary" onClick={() => {
              const until = window.prompt("Grant Pro until (YYYY-MM-DD, blank = no expiry)", "");
              if (until !== null) act("/qr/admin/grants", { user_id: selected.owner.id, plan_code: "pro", valid_until: until || null, note: "admin grant" });
            }}>Grant Pro</button>
          </div>
          <h3 className="qr-subhead">Recent catalogue saves</h3>
          <ul className="small">
            {selected.revisions.map((r, i) => (
              <li key={i}>{new Date(r.at).toLocaleString("en-IN")} — {r.counted ? "counted" : "free"} ({r.plan}) · +{r.summary.added} ~{r.summary.updated} −{r.summary.removed}</li>
            ))}
          </ul>
          <h3 className="qr-subhead">Audit history</h3>
          <ul className="small">
            {selected.audit.map((a, i) => <li key={i}>{new Date(a.at).toLocaleString("en-IN")} — {a.action}</li>)}
          </ul>
        </section>
      )}

      <section className="card">
        <h2>Plans</h2>
        <table className="admin-table">
          <thead><tr><th>Plan</th><th>Monthly updates</th><th>Display price</th><th /></tr></thead>
          <tbody>
            {plans.map((p) => (
              <tr key={p.code}>
                <td>{p.name}</td>
                <td>{p.monthly_catalogue_updates ?? "Unlimited"}</td>
                <td>{p.price_rupees ? `₹${p.price_rupees}` : "—"}</td>
                <td><button className="btn-link" onClick={() => savePlan(p)}>Edit limit</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small">The amount actually charged is set by QR_STORE_PRO_PRICE_RUPEES in the billing service.</p>
      </section>

      <section className="card">
        <h2>AI extraction failures</h2>
        {jobs.length === 0 ? <p className="muted">None.</p> : (
          <table className="admin-table">
            <thead><tr><th>When</th><th>Store</th><th>Status</th><th>Error</th><th /></tr></thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td>{new Date(j.created_at).toLocaleString("en-IN")}</td>
                  <td><button className="btn-link" onClick={() => open(j.store_id)}>{j.store_id.slice(0, 8)}</button></td>
                  <td>{j.status}</td>
                  <td>{j.error_code}: {j.error_message}</td>
                  <td><button className="btn-link" onClick={() => act(`/qr/admin/jobs/${j.id}/retry`)}>Retry</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
