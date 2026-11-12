import React from "react";
import BusinessForm from "../../components/BusinessForm";
import JobStatus from "../../components/JobStatus";
import useJobPolling from "./useJobPolling";
import { StepNav } from "./Wizard";

export default function BusinessStep({ store, setStore, onNext, onBack }) {
  useJobPolling(store, setStore);
  return (
    <section className="card" aria-labelledby="biz-title">
      <h1 id="biz-title">Your business details</h1>
      <p className="muted">Customers see these on your store. Everything is editable later from your dashboard.</p>
      <JobStatus store={store} setStore={setStore} compact />
      <BusinessForm
        store={store}
        setStore={setStore}
        extracted={store.job?.result?.business}
        onSaved={onNext}
        footer={({ save, busy }) => <StepNav onBack={onBack} onNext={save} busy={busy} />}
      />
    </section>
  );
}
