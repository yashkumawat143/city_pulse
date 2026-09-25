import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend base URL for dev proxying. Override with BACKEND_URL env if the API
// runs elsewhere. (Production/single-origin builds serve the API itself —
// see lib/api.js for how VITE_API_URL takes precedence when set.)
const BACKEND = process.env.BACKEND_URL || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // REST: forward every /api call to FastAPI so the same relative paths
      // work in dev and production and CORS is never an issue locally.
      "/api": { target: BACKEND, changeOrigin: true },
      // WebSocket: forward the live push channel (ws:// upgrade).
      "/ws": { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
});
