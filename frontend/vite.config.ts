import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The API runs on 8000. Proxying keeps the browser same-origin, so CORS
    // never bites during local development.
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true,
                       rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
