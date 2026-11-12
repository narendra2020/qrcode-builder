import React from "react";

const LEVELS = [
  { label: "Too short", className: "weak" },
  { label: "Weak", className: "weak" },
  { label: "Fair", className: "fair" },
  { label: "Good", className: "good" },
  { label: "Strong", className: "strong" },
];

export function scorePassword(password) {
  if (password.length < 8) return 0;
  let score = 1;
  if (password.length >= 12) score++;
  if (/[A-Z]/.test(password) && /[a-z]/.test(password)) score++;
  if (/\d/.test(password)) score++;
  if (/[^A-Za-z0-9]/.test(password)) score++;
  return Math.min(score, 4);
}

export default function PasswordStrengthMeter({ password }) {
  const score = scorePassword(password);
  const level = LEVELS[score];

  return (
    <div className="password-strength">
      <div className="password-strength-bar">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={`password-strength-segment ${i < score ? level.className : ""}`}
          />
        ))}
      </div>
      {password && <span className={`password-strength-label ${level.className}`}>{level.label}</span>}
    </div>
  );
}
