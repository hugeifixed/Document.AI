import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";
import { createPageTitleConfig, fallbackTitleHtml } from "./src/app/page-title-config.ts";

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), {
    name: "application-title",
    transformIndexHtml: (html) => html.replace(/<title>[^<]*<\/title>/, () =>
      fallbackTitleHtml(createPageTitleConfig(loadEnv(mode, process.cwd())))),
  }],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "next/navigation": fileURLToPath(new URL("./src/mocks/next-navigation.ts", import.meta.url)),
    },
  },
  ssr: { noExternal: ["nextstepjs", "motion"] },
  server: {
    port: 5173,
    // Django's local CORS/CSRF settings and admin link expect this origin.
    // Failing clearly is safer than silently moving the frontend to 5174.
    strictPort: true,
    proxy: {
      "/api": "http://localhost:8000",
      "^/llms\\.txt$": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/admin": "http://localhost:8000",
      // Django admin also needs its styles, scripts, and fonts on this origin.
      "/static": "http://localhost:8000",
    },
  },
  // Avoid publishing separate production source maps and retain Vite's 500 kB chunk warning.
  build: { sourcemap: false },
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
}));
