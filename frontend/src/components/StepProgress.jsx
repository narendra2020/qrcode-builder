import React from "react";
import { motion } from "framer-motion";

/** Same visual language as portfolio-builder's StepProgress, plus clickable completed steps. */
export default function StepProgress({ steps, currentIndex, maxReachedIndex, onSelect }) {
  const pct = Math.min(100, ((currentIndex + 1) / steps.length) * 100);
  return (
    <nav className="step-progress" aria-label="Setup progress">
      <div className="step-progress-bar" role="progressbar" aria-valuemin={1} aria-valuemax={steps.length} aria-valuenow={currentIndex + 1}
        aria-valuetext={`Step ${currentIndex + 1} of ${steps.length}: ${steps[currentIndex].label}`}>
        <motion.div className="step-progress-fill" animate={{ width: `${pct}%` }} transition={{ duration: 0.35, ease: [0.4, 0, 0.2, 1] }} />
      </div>
      <ol className="step-progress-labels qr-steps">
        {steps.map((s, idx) => {
          const reachable = idx <= maxReachedIndex && idx !== currentIndex;
          const cls =
            "step-progress-label" +
            (idx === currentIndex ? " step-progress-label-active" : "") +
            (idx < currentIndex ? " step-progress-label-done" : "");
          return (
            <li key={s.key}>
              {reachable ? (
                <button type="button" className={cls + " qr-step-btn"} onClick={() => onSelect(s.key)}>
                  {s.label}
                </button>
              ) : (
                <span className={cls} aria-current={idx === currentIndex ? "step" : undefined}>{s.label}</span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
