import { resolve } from "node:path";
import { defineConfig } from "vite";

// One page per Tauri window: the floating logo (index.html), the chat panel, the notice balloon.
export default defineConfig({
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  build: {
    target: "es2022",
    rollupOptions: {
      input: {
        bubble: resolve(import.meta.dirname, "index.html"),
        chat: resolve(import.meta.dirname, "chat.html"),
        notice: resolve(import.meta.dirname, "notice.html"),
      },
    },
  },
});
