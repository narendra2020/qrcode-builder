import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { errorMessage } from "../api/client";
import PasswordStrengthMeter from "../components/PasswordStrengthMeter";

export default function Signup() {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [mobileNumber, setMobileNumber] = useState("");
  const [password, setPassword] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const mobileValid = /^[6-9]\d{9}$/.test(mobileNumber);
  const passwordValid = password.length >= 8;
  const canSubmit = fullName.trim() && mobileValid && passwordValid && agreed && !loading;

  async function handleSubmit(e) {
    e.preventDefault();
    if (!canSubmit) return;
    setError("");
    setLoading(true);
    try {
      const transactionId = await signup(fullName.trim(), mobileNumber, password);
      navigate("/verify-otp", { state: { transactionId, mobileNumber } });
    } catch (err) {
      setError(errorMessage(err, "Could not sign you up. Please try again."));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-card">
      <h1>Create your digital store</h1>
      <p className="muted">
        Turn a photo of your menu or price list into a shareable store with a QR code. We'll send a one-time code to
        your WhatsApp to verify your number.
      </p>
      <form onSubmit={handleSubmit} noValidate>
        <label htmlFor="su-name">Your full name</label>
        <input id="su-name" type="text" autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} required />

        <label htmlFor="su-mobile">WhatsApp mobile number</label>
        <div className="mobile-input-group">
          <span className="mobile-input-prefix" aria-hidden="true">+91</span>
          <input
            id="su-mobile"
            type="tel"
            inputMode="numeric"
            autoComplete="tel-national"
            placeholder="9876543210"
            maxLength={10}
            value={mobileNumber}
            onChange={(e) => setMobileNumber(e.target.value.replace(/\D/g, "").slice(0, 10))}
            aria-describedby="su-mobile-hint"
            aria-invalid={mobileNumber.length === 10 && !mobileValid}
            required
          />
        </div>
        <p id="su-mobile-hint" className="muted small">
          {mobileNumber.length === 10 && !mobileValid ? "Enter a valid Indian mobile number." : "Indian (+91) mobile numbers."}
        </p>

        <label htmlFor="su-password">Password</label>
        <input id="su-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
        <PasswordStrengthMeter password={password} />
        <p className="muted small" style={{ marginTop: "0.3rem" }}>Minimum 8 characters.</p>

        <label className="checkbox-inline" style={{ display: "flex", marginTop: "0.9rem" }}>
          <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} required />
          &nbsp;I agree to the Terms of Service
        </label>

        {error && <p className="error-text" role="alert">{error}</p>}

        <button type="submit" className="btn btn-primary btn-block" disabled={!canSubmit}>
          {loading ? "Sending code..." : "Sign up"}
        </button>
      </form>

      <p className="auth-switch">
        Already have a MePage account? <Link to="/login">Log in</Link>
      </p>
    </div>
  );
}
