import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In Docker the API is reachable as http://api:8000 (set by docker-compose.override.yml);
// when running `npm run dev` on the host, it defaults to localhost.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";
const hmrClientPort = process.env.VITE_HMR_CLIENT_PORT
  ? Number(process.env.VITE_HMR_CLIENT_PORT)
  : undefined;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    // Docker on Windows: bind mounts don't emit file events, so poll instead.
    watch: process.env.VITE_USE_POLLING === "true" ? { usePolling: true, interval: 300 } : undefined,
    // The container's 5173 is published on the host as WEB_PORT (8080 by default).
    hmr: hmrClientPort ? { clientPort: hmrClientPort } : undefined,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
    },
  },
});
