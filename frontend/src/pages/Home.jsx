import React, { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import client, { errorMessage } from "../api/client";

/** Routes the owner to their store (dashboard or the resumed setup step), or starts a new one. */
export default function Home() {
  const navigate = useNavigate();
  const [state, setState] = useState({ loading: true, stores: [], error: "" });
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    client
      .get("/qr/stores")
      .then(({ data }) => setState({ loading: false, stores: data.stores, error: "" }))
      .catch((err) => setState({ loading: false, stores: [], error: errorMessage(err, "Could not load your stores.") }));
  }, []);

  async function start() {
    setCreating(true);
    try {
      const { data } = await client.post("/qr/stores", {});
      navigate(`/stores/${data.id}/setup/upload`);
    } catch (err) {
      setState((s) => ({ ...s, error: errorMessage(err) }));
      setCreating(false);
    }
  }

  if (state.loading) return <div className="card"><p className="muted">Loading your store…</p></div>;

  if (state.stores.length === 1) {
    const s = state.stores[0];
    const done = s.onboarding_step === "done" || s.first_published_at;
    return <Navigate to={done ? `/stores/${s.id}` : `/stores/${s.id}/setup/${s.onboarding_step}`} replace />;
  }

  return (
    <div className="qr-hero card">
      <div className="qr-hero-text">
        <p className="qr-eyebrow">MePage Store Builder</p>
        <h1>Your menu, online in minutes</h1>
        <p className="muted">
          Snap a photo of your menu, catalogue or price list. Our AI reads your items and prices, you check them, pick a
          design — and you get a store link and a QR code customers can scan to browse and enquire on WhatsApp.
        </p>
        <ol className="qr-how">
          <li><strong>Upload</strong> a photo of your menu or product list</li>
          <li><strong>Review</strong> the items our AI extracted</li>
          <li><strong>Publish</strong> and print your branded QR code</li>
        </ol>
        {state.error && <p className="error-text" role="alert">{state.error}</p>}
        {state.stores.length === 0 ? (
          <button className="btn btn-primary" onClick={start} disabled={creating}>
            {creating ? "Starting…" : "Create my store"}
          </button>
        ) : (
          <ul className="qr-store-list">
            {state.stores.map((s) => (
              <li key={s.id}>
                <button className="btn btn-secondary" onClick={() => navigate(`/stores/${s.id}`)}>
                  {s.name || "Untitled store"} · {s.status}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
