import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In Docker the API is reachable as http://api:8000 (set by docker-compose.override.yml);
// when running `npm run dev` on the host, it defaults to localhost.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    // Phone over Tailscale: `tailscale serve` keeps the Host header (machine.tailnet.ts.net),
    // which Vite rejects unless it is listed. localhost and IPs are always allowed.
    allowedHosts: [".ts.net"],
    // Docker on Windows: bind mounts don't emit file events, so poll instead.
    watch: process.env.VITE_USE_POLLING === "true" ? { usePolling: true, interval: 300 } : undefined,
    // No hmr.clientPort: the HMR socket then uses the page's own host and port, which is
    // right both for http://localhost:8080 and for https://machine.tailnet.ts.net (443).
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
    },
  },
});
