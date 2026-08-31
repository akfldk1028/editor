import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const frontendPort = Number(process.env.DWG_FRONTEND_PORT ?? 4173);
const gatewayPort = Number(process.env.DWG_GATEWAY_PORT ?? 4317);

export default defineConfig({
  plugins: [react()],
  server: {
    port: frontendPort,
    strictPort: true,
    proxy: {
      "/api": `http://127.0.0.1:${gatewayPort}`
    }
  }
});
