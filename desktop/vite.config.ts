import { resolve } from "node:path";
import { defineConfig } from "vite";

// Two pages, one per Tauri window: the floating logo (index.html) and the chat panel.
export default defineConfig({
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  build: {
    target: "es2022",
    rollupOptions: {
      input: {
        bubble: resolve(import.meta.dirname, "index.html"),
        chat: resolve(import.meta.dirname, "chat.html"),
      },
    },
  },
});
