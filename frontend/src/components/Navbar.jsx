import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";

const SUN_SVG = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <circle cx="12" cy="12" r="4.3" />
    <path
      d="M12 2.5v2.6M12 18.9v2.6M4.2 4.2l1.9 1.9M17.9 17.9l1.9 1.9M2.5 12h2.6M18.9 12h2.6M4.2 19.8l1.9-1.9M17.9 6.1l1.9-1.9"
      strokeLinecap="round"
    />
  </svg>
);

const MOON_SVG = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z" />
  </svg>
);

export default function Navbar() {
  const { user, logout, isAdmin, ghost } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();

  return (
    <header className="navbar">
      <Link to="/" className="navbar-brand">
        <svg className="navbar-brandmark" viewBox="0 0 64 64" aria-hidden="true">
          <rect width="64" height="64" rx="17" fill="#6657ed" />
          <path d="M15 44V20h7l10 13 10-13h7v24h-8V31l-9 11-9-11v13z" fill="#fff" />
          <circle cx="49" cy="16" r="5" fill="#b9f47a" />
        </svg>
        <span>MePage <span className="qr-nav-sub">Store Builder</span></span>
      </Link>
      <div className="navbar-right">
        {isAdmin && (
          <Link to="/admin" className="btn-link">
            Admin
          </Link>
        )}
        <button
          type="button"
          className="icon-btn"
          onClick={toggleTheme}
          aria-label="Toggle classic/dark mode"
          title={theme === "dark" ? "Switch to classic mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? MOON_SVG : SUN_SVG}
        </button>
        {user && (
          <>
            <span className="navbar-user qr-hide-sm">
              <span className="role-badge">{user.full_name}</span>
            </span>
            <button
              className="btn-link"
              onClick={async () => {
                await logout();
                navigate(ghost ? "/admin" : "/login");
              }}
            >
              Log out
            </button>
          </>
        )}
      </div>
    </header>
  );
}
