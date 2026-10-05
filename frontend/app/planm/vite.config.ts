import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

/**
 * One origin, three surfaces.
 *
 * `/dwg` and `/planm` are rendered by this app. `/editor` is the Pascal 3D
 * editor — a separate Next.js application, proxied in so the whole product
 * answers on a single address. It runs with PASCAL_BASE_PATH=/editor, so it
 * serves its own pages and assets under that prefix and nothing needs
 * rewriting here.
 */
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api/v1": loadEnv(mode, '.', 'EDITOR_').EDITOR_BACKEND_URL || "http://127.0.0.1:18449",
      "/api": "http://127.0.0.1:4317",
      // ws for Next's dev hot-reload socket.
      "/editor": { target: "http://127.0.0.1:3002", ws: true },
    },
  },
}));
