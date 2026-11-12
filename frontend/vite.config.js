import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api/qr/* goes to the QR Store Builder backend; every other /api/* path
// (auth, number verification, billing) goes to portfolio-builder, so login,
// sessions and payments are the existing MePage implementations.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5175,
    host: true,
    proxy: {
      "/api/qr": {
        target: process.env.VITE_QR_API_PROXY_TARGET || "http://localhost:8002",
        changeOrigin: true,
      },
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8001",
        changeOrigin: true,
      },
    },
  },
});
