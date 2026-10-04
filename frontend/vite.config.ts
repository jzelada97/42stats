/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Las páginas cuelgan de /static/ (lo sirve FastAPI); el HTML de cada ruta es el mismo index.html.
export default defineConfig({
  base: "/static/",
  plugins: [react()],
  build: { outDir: "../src/stats42/web_app", emptyOutDir: true, sourcemap: false, target: "es2022" },
  server: { port: 5173, proxy: { "/api": "http://localhost:8042", "/auth": "http://localhost:8042" } },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
