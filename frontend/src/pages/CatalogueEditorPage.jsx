import React, { useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import { useMeta, useStore } from "../api/stores";
import CatalogueEditor from "../components/CatalogueEditor";

export default function CatalogueEditorPage() {
  const { storeId } = useParams();
  const { store, setStore, error, reload } = useStore(storeId);
  const meta = useMeta();
  const onUsage = useCallback((usage) => setStore((s) => (s ? { ...s, usage } : s)), [setStore]);

  if (error) return <div className="card"><p className="error-text" role="alert">{error}</p></div>;
  if (!store || !meta) return <div className="card"><p className="muted">Loading…</p></div>;
  const category = meta.categories.find((c) => c.key === store.category_key);
  const live = !!store.first_published_at;

  return (
    <section className="card" aria-labelledby="ce-title">
      <Link to={`/stores/${storeId}`} className="btn-link">← Dashboard</Link>
      <h1 id="ce-title">{category?.catalogue_noun || "Catalogue"}</h1>
      <p className="muted">
        {live && store.status === "published"
          ? "Edit as much as you like — changes go live together when you save."
          : "Make your changes and save."}
      </p>
      <CatalogueEditor storeId={storeId} meta={meta} category={category} isLive={live} onSaved={() => reload()} onUsage={onUsage} />
    </section>
  );
}
