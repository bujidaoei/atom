import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function publicBase(): string {
  const raw = process.env.VITE_BASE?.trim();
  if (!raw || raw === "/") return "/";
  return `/${raw.replace(/^\/+|\/+$/g, "")}/`;
}

const backend = process.env.VITE_BACKEND?.trim() || "http://127.0.0.1:8000";

export default defineConfig({
  base: publicBase(),
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: false },
      "/preview": { target: backend, changeOrigin: false },
      "/p": { target: backend, changeOrigin: false },
    },
  },
});
