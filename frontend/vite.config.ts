import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function publicBase(): string {
  const raw = process.env.VITE_BASE?.trim();
  if (!raw || raw === "/") return "/";
  return `/${raw.replace(/^\/+|\/+$/g, "")}/`;
}

export default defineConfig({
  base: publicBase(),
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
