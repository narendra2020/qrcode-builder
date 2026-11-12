import React from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

/** Persistent strip shown while an admin is managing a store as its owner. */
export default function GhostBanner() {
  const { ghost, exitGhost } = useAuth();
  const navigate = useNavigate();
  if (!ghost) return null;
  return (
    <div className="ghost-banner" role="status">
      <span>
        👻 Managing <strong>{ghost.ownerName}</strong>'s account as admin. Changes are logged under your name.
        Billing and account settings are read-only.
      </span>
      <button type="button" className="btn btn-secondary" onClick={async () => { await exitGhost(); navigate("/admin"); }}>
        Exit ghost mode
      </button>
    </div>
  );
}
