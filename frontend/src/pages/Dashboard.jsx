import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import client, { errorMessage } from "../api/client";
import { useMeta, useStore } from "../api/stores";
import BusinessForm from "../components/BusinessForm";
import BrandingForm from "../components/BrandingForm";
import QrPanel from "../components/QrPanel";
import SplitBillSettings from "../components/SplitBillSettings";
import SplitBillList from "../components/SplitBillList";
import JobStatus from "../components/JobStatus";
import { UsageBar } from "../components/CatalogueEditor";
import TemplateStep from "./wizard/TemplateStep";
import useJobPolling from "./wizard/useJobPolling";

const TABS = [
  ["overview", "Overview"],
  ["info", "Store info"],
  ["design", "Design & branding"],
  ["splitbill", "Split Bill"],
  ["plan", "Plan"],
];

export default function Dashboard() {
  const { storeId } = useParams();
  const navigate = useNavigate();
  const { store, setStore, error, reload } = useStore(storeId);
  const meta = useMeta();
  const [tab, setTab] = useState("overview");
  const [activity, setActivity] = useState(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  useJobPolling(store, setStore);

  useEffect(() => {
    client.get(`/qr/stores/${storeId}/activity`).then(({ data }) => setActivity(data)).catch(() => {});
  }, [storeId]);

  if (error) return <div className="card"><p className="error-text" role="alert">{error}</p></div>;
  if (!store || !meta) return <div className="card"><p className="muted">Loading dashboard…</p></div>;

  if (!store.first_published_at && store.status !== "suspended") {
    return (
      <div className="card">
        <h1>{store.name || "Your store"} isn't published yet</h1>
        <p className="muted">Finish setup to get your store link and QR code.</p>
        <button className="btn btn-primary" onClick={() => navigate(`/stores/${storeId}/setup/${store.onboarding_step === "done" ? "review" : store.onboarding_step}`)}>
          Continue setup
        </button>
      </div>
    );
  }

  const live = store.status === "published";
  const category = meta.categories.find((c) => c.key === store.category_key);

  async function toggle() {
    if (live && !window.confirm("Unpublish your store? Customers scanning your QR code will see a 'not found' page until you republish.")) return;
    setBusy(true);
    setActionError("");
    try {
      const { data } = await client.post(`/qr/stores/${storeId}/${live ? "unpublish" : "publish"}`);
      setStore(data);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="qr-dash">
      <header className="qr-dash-head">
        <div>
          <p className="qr-eyebrow">{category ? `${category.icon} ${category.label}` : "Store"}</p>
          <h1>{store.name}</h1>
          <span className={`qr-status qr-status-${store.status}`}>{statusLabel(store.status)}</span>
        </div>
        <div className="qr-inline-actions">
          {live && <a className="btn btn-secondary" href={store.public_url} target="_blank" rel="noopener noreferrer">View store ↗</a>}
          {store.status !== "suspended" && (
            <button type="button" className={live ? "btn btn-secondary" : "btn btn-primary"} onClick={toggle} disabled={busy}>
              {busy ? "…" : live ? "Unpublish" : "Republish"}
            </button>
          )}
        </div>
      </header>

      {store.status === "suspended" && (
        <div className="qr-job qr-job-error" role="alert">
          <strong>This store is suspended.</strong> {store.suspended_reason} Please contact MePage support.
        </div>
      )}
      {actionError && <p className="error-text" role="alert">{actionError}</p>}
      {store.readiness.length > 0 && (
        <div className="qr-job qr-job-warn" role="note">
          <strong>Needs attention</strong>
          <ul className="small">{store.readiness.map((i) => <li key={i.message}>{i.message}</li>)}</ul>
        </div>
      )}

      <div className="qr-tabs" role="tablist" aria-label="Dashboard sections">
        {TABS.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} className="qr-tab" onClick={() => setTab(key)}>{label}</button>
        ))}
        <Link className="qr-tab" to={`/stores/${storeId}/catalogue`}>Catalogue ({store.item_count})</Link>
      </div>

      {tab === "overview" && (
        <div className="qr-dash-grid">
          <section className="card">
            <h2>Store link & QR code</h2>
            <QrPanel store={store} live={live} />
          </section>
          <section className="card">
            <h2>{category?.catalogue_noun || "Catalogue"}</h2>
            <p className="qr-big">{store.item_count} <span className="muted small">items</span></p>
            <UsageBar usage={store.usage} storeId={storeId} />
            <JobStatus store={store} setStore={setStore} compact />
            <div className="qr-inline-actions">
              <Link className="btn btn-primary" to={`/stores/${storeId}/catalogue`}>Edit items & prices</Link>
            </div>
          </section>
          <section className="card">
            <h2>Activity (last 30 days)</h2>
            {activity && activity.days.length ? (
              <>
                <div className="qr-stats">
                  <Stat n={activity.totals.views} label="Store visits" />
                  <Stat n={activity.totals.item_enquiries} label="Item enquiries" />
                  <Stat n={activity.totals.cart_enquiries} label="List enquiries" />
                </div>
                <p className="muted small">{activity.note}</p>
              </>
            ) : (
              <p className="muted small">No visits yet. Share your link or put your QR code where customers will see it.</p>
            )}
          </section>
        </div>
      )}

      {tab === "info" && (
        <section className="card">
          <h2>Store information</h2>
          <BusinessForm store={store} setStore={setStore} onSaved={() => reload()} submitLabel="Save store info" />
        </section>
      )}

      {tab === "design" && (
        <>
          <section className="card">
            <h2>Store design</h2>
            <TemplateStep store={store} setStore={setStore} embedded />
          </section>
          <section className="card">
            <h2>Branding</h2>
            <BrandingForm store={store} setStore={setStore} meta={meta} />
            <p className="muted small">Design and branding changes don't use your monthly catalogue updates.</p>
          </section>
        </>
      )}

      {tab === "splitbill" && (
        <>
          <SplitBillSettings store={store} setStore={setStore} meta={meta} />
          {store.payment.split_bill.eligible && <SplitBillList storeId={storeId} />}
        </>
      )}

      {tab === "plan" && (
        <section className="card">
          <h2>Plan: {store.usage.plan.name}</h2>
          {store.usage.plan.valid_until && (
            <p className="muted">Active until {new Date(store.usage.plan.valid_until).toLocaleDateString("en-IN")}</p>
          )}
          <UsageBar usage={store.usage} storeId={storeId} />
          <p className="muted small">
            A catalogue update is one saved change to your live items and prices — however many items you edit in that
            save. Design, branding and store-info edits are free. Counts reset at midnight IST on the 1st of each month.
          </p>
          {!store.usage.unlimited && <Link className="btn btn-primary" to={`/stores/${storeId}/upgrade`}>Upgrade plan</Link>}
        </section>
      )}
    </div>
  );
}

function Stat({ n, label }) {
  return (
    <div className="qr-stat">
      <span className="qr-big">{n}</span>
      <span className="muted small">{label}</span>
    </div>
  );
}

function statusLabel(s) {
  return { published: "● Live", unpublished: "Unpublished", draft: "Draft", suspended: "Suspended" }[s] || s;
}
