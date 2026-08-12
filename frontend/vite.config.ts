/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vite";

const release = readFileSync(resolve(__dirname, "../VERSION"), "utf8").trim();
const sha = process.env.RENDER_GIT_COMMIT || process.env.GITHUB_SHA || "dev";
const shortSha = sha === "dev" ? sha : sha.slice(0, 7);
const buildId = `${release}+${shortSha}`;

// Vitest config co-located (IMPLEMENTATION §2: vitest + Testing Library, no snapshots).
export default defineConfig({
  plugins: [react()],
  define: {
    "import.meta.env.VITE_APP_VERSION": JSON.stringify(buildId),
    "import.meta.env.VITE_RELEASE_VERSION": JSON.stringify(release),
    "import.meta.env.VITE_BUILD_SHA": JSON.stringify(sha),
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    css: false,
    // Placeholder credentials so modules importing the supabase client load in
    // tests; no test talks to a real backend.
    env: {
      VITE_SUPABASE_URL: "http://localhost:54321",
      VITE_SUPABASE_ANON_KEY: "test-anon-key",
    },
  },
});
