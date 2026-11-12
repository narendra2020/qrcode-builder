import React, { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { errorMessage } from "../api/client";

const RESEND_COOLDOWN_SECONDS = 120;

export default function VerifyOtp() {
  const { verifyOtp, resendOtp } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [transactionId, setTransactionId] = useState(location.state?.transactionId || "");
  const [otp, setOtp] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [resending, setResending] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(RESEND_COOLDOWN_SECONDS);

  useEffect(() => {
    const timer = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(timer);
  }, []);

  if (!transactionId) return <Navigate to="/signup" replace />;

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await verifyOtp(transactionId, otp);
      navigate("/");
    } catch (err) {
      setError(errorMessage(err, "Invalid or expired code."));
    } finally {
      setLoading(false);
    }
  }

  async function handleResend() {
    setError("");
    setResending(true);
    try {
      setTransactionId(await resendOtp(transactionId));
      setSecondsLeft(RESEND_COOLDOWN_SECONDS);
    } catch (err) {
      setError(errorMessage(err, "Could not resend the code."));
    } finally {
      setResending(false);
    }
  }

  const mm = String(Math.floor(secondsLeft / 60)).padStart(2, "0");
  const ss = String(secondsLeft % 60).padStart(2, "0");

  return (
    <div className="auth-card">
      <h1>Enter your code</h1>
      <p className="muted">
        We sent a 6-digit code on WhatsApp to +91 {location.state?.mobileNumber || "your number"}. It's valid for 10
        minutes.
      </p>
      <form onSubmit={handleSubmit}>
        <label htmlFor="otp">One-time code</label>
        <input
          id="otp"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={otp}
          onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
          required
        />
        {error && <p className="error-text" role="alert">{error}</p>}
        <button type="submit" className="btn btn-primary btn-block" disabled={loading || otp.length !== 6}>
          {loading ? "Verifying..." : "Verify"}
        </button>
        {secondsLeft > 0 ? (
          <p className="muted small" style={{ marginTop: "0.8rem", textAlign: "center" }}>
            Resend code in {mm}:{ss}
          </p>
        ) : (
          <button type="button" className="btn-link" style={{ display: "block", margin: "0.8rem auto 0" }} onClick={handleResend} disabled={resending}>
            {resending ? "Resending..." : "Resend code"}
          </button>
        )}
      </form>
      {import.meta.env.VITE_OTP_MODE === "dev_fixed" && <p className="dev-otp-hint">Dev mode: use code 123456</p>}
    </div>
  );
}
