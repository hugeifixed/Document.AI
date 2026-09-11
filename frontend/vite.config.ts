import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "next/navigation": fileURLToPath(new URL("./src/mocks/next-navigation.ts", import.meta.url)),
    },
  },
  ssr: { noExternal: ["nextstepjs", "motion"] },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/admin": "http://localhost:8000",
      // Django admin also needs its styles, scripts, and fonts on this origin.
      "/static": "http://localhost:8000",
    },
  },
  build: { sourcemap: false, chunkSizeWarningLimit: 1500 },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov"],
      reportsDirectory: "coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/api/types.ts", "src/main.tsx", "src/mocks/**", "src/test/**"],
      thresholds: {
        statements: 80,
        branches: 70,
        functions: 70,
        lines: 85,
      },
    },
  },
});
