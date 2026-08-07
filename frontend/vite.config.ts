import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@dwg/workspace": fileURLToPath(new URL("../external/dwg-intelligence/apps/workspace/src/public.ts", import.meta.url)),
      "@dwg/contracts": fileURLToPath(new URL("../external/dwg-intelligence/packages/contracts/src/index.ts", import.meta.url)),
    },
  },
  server: {
    fs: {
      allow: [dirname(fileURLToPath(new URL("../external/dwg-intelligence", import.meta.url)))],
    },
    port: 5173,
    proxy: {
      "/api/v1": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:4317",
    },
  },
});
