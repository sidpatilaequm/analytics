import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api is proxied in dev so there is no CORS preflight while developing.
// For production, `npm run build` and serve dist/ from the same origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://localhost:5001", changeOrigin: true } },
  },
});
