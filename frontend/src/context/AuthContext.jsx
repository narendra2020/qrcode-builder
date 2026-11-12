import React, { createContext, useContext, useState, useCallback } from "react";
import client, { clearSession, enterGhostSession, getGhost, restoreAdminSession } from "../api/client";

// Thin wrapper over portfolio-builder's existing auth endpoints
// (/api/auth/*): same signup + WhatsApp OTP, password login, refresh
// rotation and logout. No separate account system.
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const raw = localStorage.getItem("auth_user");
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });

  const [ghost, setGhost] = useState(getGhost);

  // Admin: manage a store as its owner (short-lived token, audited, read-only account/billing).
  const startGhost = useCallback(async (storeId) => {
    const { data } = await client.post(`/qr/admin/stores/${storeId}/ghost-login`);
    enterGhostSession(data);
    setUser(data.user);
    setGhost(getGhost());
    return data.store_id;
  }, []);

  const exitGhost = useCallback(async () => {
    try {
      await client.post("/qr/admin/ghost-exit");
    } catch (e) {
      // best-effort audit entry; leave regardless
    }
    setUser(restoreAdminSession());
    setGhost(null);
  }, []);

  const applySession = useCallback((data) => {
    localStorage.setItem("access_token", data.access_token);
    localStorage.setItem("refresh_token", data.refresh_token);
    localStorage.setItem("auth_user", JSON.stringify(data.user));
    localStorage.setItem("onboarding_status", data.onboarding_status);
    setUser(data.user);
  }, []);

  const signup = useCallback(async (fullName, mobileNumber, password) => {
    const { data } = await client.post("/auth/signup", {
      full_name: fullName,
      mobile_number: mobileNumber,
      password,
    });
    return data.transaction_id;
  }, []);

  const resendOtp = useCallback(async (transactionId) => {
    const { data } = await client.post("/auth/otp/resend", { transaction_id: transactionId });
    return data.transaction_id;
  }, []);

  const verifyOtp = useCallback(
    async (transactionId, otp) => {
      const { data } = await client.post("/auth/otp/verify", { transaction_id: transactionId, otp });
      applySession(data);
      return data;
    },
    [applySession]
  );

  const login = useCallback(
    async (mobileNumber, password) => {
      const { data } = await client.post("/auth/login", { mobile_number: mobileNumber, password });
      applySession(data);
      return data;
    },
    [applySession]
  );

  const requestPasswordReset = useCallback(async (mobileNumber) => {
    const { data } = await client.post("/auth/password-reset/request", { mobile_number: mobileNumber });
    return data.transaction_id;
  }, []);

  const verifyPasswordReset = useCallback(
    async (transactionId, otp, newPassword) => {
      const { data } = await client.post("/auth/password-reset/verify", {
        transaction_id: transactionId,
        otp,
        new_password: newPassword,
      });
      applySession(data);
      return data;
    },
    [applySession]
  );

  const logout = useCallback(async () => {
    if (getGhost()) {  // "Log out" inside a ghost session just returns to the admin's own session
      await exitGhost();
      return;
    }
    const refreshToken = localStorage.getItem("refresh_token");
    if (refreshToken) {
      try {
        await client.post("/auth/logout", { refresh_token: refreshToken });
      } catch (e) {
        // best-effort — proceed to clear local state regardless
      }
    }
    clearSession();
    setUser(null);
  }, [exitGhost]);

  return (
    <AuthContext.Provider
      value={{
        user,
        signup,
        resendOtp,
        verifyOtp,
        login,
        requestPasswordReset,
        verifyPasswordReset,
        logout,
        ghost,
        startGhost,
        exitGhost,
        isAdmin: user?.role === "admin" || user?.role === "super_admin",
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
