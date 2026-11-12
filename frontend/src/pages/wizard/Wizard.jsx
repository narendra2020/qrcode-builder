import React, { useMemo } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { useMeta, useStore, patchStore } from "../../api/stores";
import StepProgress from "../../components/StepProgress";
import UploadStep from "./UploadStep";
import CategoryStep from "./CategoryStep";
import BusinessStep from "./BusinessStep";
import TemplateStep from "./TemplateStep";
import CatalogueStep from "./CatalogueStep";
import BrandingStep from "./BrandingStep";
import ReviewStep from "./ReviewStep";

// The step list is data: adding a step means one entry here plus a component.
export const STEPS = [
  { key: "upload", label: "Upload", Component: UploadStep },
  { key: "category", label: "Category", Component: CategoryStep },
  { key: "business", label: "Details", Component: BusinessStep },
  { key: "template", label: "Design", Component: TemplateStep },
  { key: "catalogue", label: "Items", Component: CatalogueStep },
  { key: "branding", label: "Branding", Component: BrandingStep },
  { key: "review", label: "Publish", Component: ReviewStep },
];

export default function Wizard() {
  const { storeId, step } = useParams();
  const navigate = useNavigate();
  const { store, setStore, error, reload } = useStore(storeId);
  const meta = useMeta();

  const index = STEPS.findIndex((s) => s.key === step);
  const savedIndex = store ? Math.max(0, STEPS.findIndex((s) => s.key === store.onboarding_step)) : 0;
  const maxReached = useMemo(() => Math.max(index, savedIndex), [index, savedIndex]);

  if (index === -1) return <Navigate to={`/stores/${storeId}/setup/upload`} replace />;
  if (error) return <div className="card"><p className="error-text" role="alert">{error}</p></div>;
  if (!store || !meta) return <div className="card"><p className="muted">Loading your store…</p></div>;

  async function go(key, { persist = true } = {}) {
    const target = STEPS.findIndex((s) => s.key === key);
    // Persist furthest progress so the setup resumes here after logout / on another device.
    if (persist && target > savedIndex && !store.first_published_at) {
      try {
        setStore(await patchStore(storeId, { onboarding_step: key }));
      } catch {
        /* non-blocking */
      }
    }
    navigate(`/stores/${storeId}/setup/${key}`);
    window.scrollTo({ top: 0 });
  }

  const { Component } = STEPS[index];
  const next = STEPS[index + 1]?.key;
  const back = STEPS[index - 1]?.key;

  return (
    <div className="qr-wizard">
      <StepProgress steps={STEPS} currentIndex={index} maxReachedIndex={maxReached} onSelect={(k) => go(k, { persist: false })} />
      <Component
        store={store}
        setStore={setStore}
        reload={reload}
        meta={meta}
        onNext={next ? () => go(next) : () => navigate(`/stores/${storeId}`)}
        onBack={back ? () => go(back, { persist: false }) : null}
        goTo={(k) => go(k, { persist: false })}
      />
    </div>
  );
}

/** Shared Back / Next footer. */
export function StepNav({ onBack, onNext, nextLabel = "Next", nextDisabled, busy, hint }) {
  return (
    <div className="qr-step-nav">
      {onBack ? (
        <button type="button" className="btn btn-secondary" onClick={onBack} disabled={busy}>
          Back
        </button>
      ) : (
        <span />
      )}
      <div className="qr-step-nav-right">
        {hint && <span className="muted small">{hint}</span>}
        <button type="button" className="btn btn-primary" onClick={onNext} disabled={nextDisabled || busy}>
          {busy ? "Saving…" : nextLabel}
        </button>
      </div>
    </div>
  );
}
