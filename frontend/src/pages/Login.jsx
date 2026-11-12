import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { errorMessage } from "../api/client";

export default function Login() {
  const { login, requestPasswordReset, verifyPasswordReset } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const expired = new URLSearchParams(location.search).get("expired");
  const [mobileNumber, setMobileNumber] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState("login");
  const [resetStep, setResetStep] = useState("request");
  const [resetTransactionId, setResetTransactionId] = useState("");
  const [otp, setOtp] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState(expired ? "Your session expired. Please log in again." : "");
  const [loading, setLoading] = useState(false);

  const mobileValid = /^\d{10}$/.test(mobileNumber);
  const isLogin = mode === "login";
  const canSubmit = isLogin
    ? mobileValid && password && !loading
    : resetStep === "request"
      ? mobileValid && !loading
      : mobileValid && /^\d{6}$/.test(otp) && newPassword.length >= 8 && !loading;
  const destination = location.state?.from || "/";

  function switchMode(next) {
    setMode(next);
    setResetStep("request");
    setResetTransactionId("");
    setOtp("");
    setNewPassword("");
    setPassword("");
    setError("");
    setInfo("");
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!canSubmit) return;
    setInfo("");
    setError("");
    setLoading(true);
    try {
      if (isLogin) {
        await login(mobileNumber, password);
        navigate(destination);
      } else if (resetStep === "request") {
        setResetTransactionId(await requestPasswordReset(mobileNumber));
        setResetStep("verify");
        setInfo("We sent a 6-digit OTP to your WhatsApp number.");
      } else {
        await verifyPasswordReset(resetTransactionId, otp, newPassword);
        navigate(destination);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-card">
      <h1>{isLogin ? "Welcome back" : "Reset your password"}</h1>
      <p className="muted">
        {isLogin
          ? "Log in with your MePage mobile number and password."
          : resetStep === "request"
            ? "Enter your registered mobile number to receive an OTP on WhatsApp."
            : "Enter the OTP you received on WhatsApp and choose a new password."}
      </p>
      <form onSubmit={handleSubmit}>
        <label htmlFor="li-mobile">Mobile number</label>
        <div className="mobile-input-group">
          <span className="mobile-input-prefix" aria-hidden="true">+91</span>
          <input
            id="li-mobile"
            type="tel"
            inputMode="numeric"
            autoComplete="tel-national"
            placeholder="9876543210"
            maxLength={10}
            value={mobileNumber}
            onChange={(e) => setMobileNumber(e.target.value.replace(/\D/g, "").slice(0, 10))}
            required
          />
        </div>
        {isLogin ? (
          <>
            <label htmlFor="li-password">Password</label>
            <input id="li-password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </>
        ) : (
          resetStep === "verify" && (
            <>
              <label htmlFor="li-otp">OTP</label>
              <input id="li-otp" type="tel" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))} required />
              <label htmlFor="li-newpw">New password</label>
              <input id="li-newpw" type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)}
                placeholder="At least 8 characters" required />
            </>
          )
        )}
        {error && <p className="error-text" role="alert">{error}</p>}
        {info && <p className="success-text" role="status">{info}</p>}
        <button type="submit" className="btn btn-primary btn-block" disabled={!canSubmit}>
          {isLogin ? (loading ? "Logging in..." : "Log in") : resetStep === "request" ? (loading ? "Sending OTP..." : "Send OTP") : (loading ? "Resetting..." : "Reset password")}
        </button>
      </form>
      {isLogin ? (
        <>
          <p className="auth-switch">
            <button type="button" className="btn-link" onClick={() => switchMode("reset")}>Forgot password? Reset using WhatsApp OTP</button>
          </p>
          <p className="auth-switch">Don't have an account? <Link to="/signup">Sign up</Link></p>
        </>
      ) : (
        <p className="auth-switch">
          <button type="button" className="btn-link" onClick={() => switchMode("login")}>Back to login</button>
        </p>
      )}
    </div>
  );
}
