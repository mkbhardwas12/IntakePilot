import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Full URL override for containers (e.g. http://api:8000 in docker-compose,
// where "localhost" would be the web container itself); port-only override
// for local runs.
const apiTarget =
  process.env.INTAKEPILOT_API_URL ??
  `http://localhost:${process.env.INTAKEPILOT_API_PORT ?? "8000"}`;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
      "/health": { target: apiTarget, changeOrigin: true }
    }
  }
});
