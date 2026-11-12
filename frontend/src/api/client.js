import axios from "axios";

// Same token storage + refresh-on-401 flow as portfolio-builder's client:
// tokens are issued by the shared MePage auth service.
const client = axios.create({ baseURL: "/api" });

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshing = null;

client.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;
    // Ghost (admin-as-owner) sessions have no refresh token: on expiry, drop back to the admin's own session.
    if (error.response?.status === 401 && isGhost() && !original?.url?.startsWith("/auth/")) {
      restoreAdminSession();
      window.location.href = "/admin?ghost_expired=1";
      return Promise.reject(error);
    }
    if (error.response?.status === 401 && original && !original._retry && !original.url?.startsWith("/auth/")) {
      original._retry = true;
      const refreshToken = localStorage.getItem("refresh_token");
      if (refreshToken) {
        try {
          // Single in-flight refresh: refresh tokens rotate, so parallel
          // refreshes would trip reuse detection and revoke the session.
          refreshing =
            refreshing ||
            axios.post("/api/auth/token/refresh", { refresh_token: refreshToken }).finally(() => {
              setTimeout(() => (refreshing = null), 0);
            });
          const { data } = await refreshing;
          localStorage.setItem("access_token", data.access_token);
          localStorage.setItem("refresh_token", data.refresh_token);
          original.headers.Authorization = `Bearer ${data.access_token}`;
          return client(original);
        } catch (e) {
          clearSession();
          window.location.href = "/login?expired=1";
        }
      } else {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

const GHOST_KEY = "ghost_session";
const SESSION_KEYS = ["access_token", "refresh_token", "auth_user", "onboarding_status"];

export function getGhost() {
  try {
    return JSON.parse(localStorage.getItem(GHOST_KEY) || "null");
  } catch {
    return null;
  }
}
export function isGhost() {
  return !!getGhost();
}

/** Swaps in the owner's short-lived ghost token, remembering the admin's own session. */
export function enterGhostSession(data) {
  const backup = {};
  SESSION_KEYS.forEach((k) => (backup[k] = localStorage.getItem(k)));
  localStorage.setItem(GHOST_KEY, JSON.stringify({
    backup, ownerName: data.user.full_name, storeId: data.store_id,
    expiresAt: Date.now() + data.expires_in * 1000,
  }));
  localStorage.setItem("access_token", data.access_token);
  localStorage.removeItem("refresh_token");
  localStorage.setItem("auth_user", JSON.stringify(data.user));
}

/** Restores the admin's own session; returns the restored user (or null). */
export function restoreAdminSession() {
  const ghost = getGhost();
  localStorage.removeItem(GHOST_KEY);
  if (!ghost) return null;
  SESSION_KEYS.forEach((k) => {
    if (ghost.backup[k] == null) localStorage.removeItem(k);
    else localStorage.setItem(k, ghost.backup[k]);
  });
  try {
    return JSON.parse(ghost.backup.auth_user);
  } catch {
    return null;
  }
}

export function clearSession() {
  localStorage.removeItem(GHOST_KEY);
  ["access_token", "refresh_token", "auth_user", "onboarding_status"].forEach((k) => localStorage.removeItem(k));
}

/** Turns any API error into one user-facing sentence. */
export function errorMessage(err, fallback = "Something went wrong. Please try again.") {
  const detail = err?.response?.data?.detail;
  if (!detail) {
    if (err?.response?.status === 429) return "Too many requests. Please wait a moment and try again.";
    if (!err?.response) return "You appear to be offline. Check your connection and try again.";
    return fallback;
  }
  if (typeof detail === "string") return detail;
  if (detail.message) return detail.message;
  return fallback;
}

export default client;
