import React from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import ProtectedRoute from "./components/ProtectedRoute.jsx";
import Navbar from "./components/Navbar.jsx";
import GhostBanner from "./components/GhostBanner.jsx";
import PageTransition from "./components/PageTransition.jsx";
import Signup from "./pages/Signup.jsx";
import Login from "./pages/Login.jsx";
import VerifyOtp from "./pages/VerifyOtp.jsx";
import Home from "./pages/Home.jsx";
import Wizard from "./pages/wizard/Wizard.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import CatalogueEditorPage from "./pages/CatalogueEditorPage.jsx";
import Upgrade from "./pages/Upgrade.jsx";
import AdminStores from "./pages/AdminStores.jsx";
import { useAuth } from "./context/AuthContext.jsx";

export default function App() {
  const { user } = useAuth();
  const location = useLocation();

  return (
    <>
      <GhostBanner />
      <Navbar />
      <AnimatePresence mode="wait" initial={false}>
        <Routes location={location} key={location.pathname.split("/").slice(0, 4).join("/")}>
          <Route path="/signup" element={<PageTransition><Signup /></PageTransition>} />
          <Route path="/login" element={<PageTransition><Login /></PageTransition>} />
          <Route path="/verify-otp" element={<PageTransition><VerifyOtp /></PageTransition>} />

          <Route path="/" element={<ProtectedRoute><PageTransition className="page-container"><Home /></PageTransition></ProtectedRoute>} />
          <Route
            path="/stores/:storeId/setup/:step"
            element={<ProtectedRoute><PageTransition className="page-container qr-wide"><Wizard /></PageTransition></ProtectedRoute>}
          />
          <Route
            path="/stores/:storeId"
            element={<ProtectedRoute><PageTransition className="page-container qr-wide"><Dashboard /></PageTransition></ProtectedRoute>}
          />
          <Route
            path="/stores/:storeId/catalogue"
            element={<ProtectedRoute><PageTransition className="page-container qr-wide"><CatalogueEditorPage /></PageTransition></ProtectedRoute>}
          />
          <Route
            path="/stores/:storeId/upgrade"
            element={<ProtectedRoute><PageTransition className="page-container"><Upgrade /></PageTransition></ProtectedRoute>}
          />
          <Route
            path="/admin"
            element={<ProtectedRoute adminOnly><PageTransition className="page-container qr-wide"><AdminStores /></PageTransition></ProtectedRoute>}
          />
          <Route path="*" element={<Navigate to={user ? "/" : "/signup"} replace />} />
        </Routes>
      </AnimatePresence>
    </>
  );
}
