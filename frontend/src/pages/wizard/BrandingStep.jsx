import React from "react";
import BrandingForm from "../../components/BrandingForm";
import { StepNav } from "./Wizard";

export default function BrandingStep({ store, setStore, meta, onNext, onBack }) {
  return (
    <section className="card" aria-labelledby="brand-title">
      <h1 id="brand-title">Make it yours</h1>
      <p className="muted">Add your logo and colours. The design's defaults look great too — you can skip this.</p>
      <BrandingForm
        store={store}
        setStore={setStore}
        meta={meta}
        footer={({ save, busy }) => (
          <StepNav onBack={onBack} onNext={async () => (await save()) && onNext()} busy={busy} />
        )}
      />
    </section>
  );
}
