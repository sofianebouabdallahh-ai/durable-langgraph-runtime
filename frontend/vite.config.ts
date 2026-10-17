import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `pnpm dev` proxies /api to a local API (`make api`), exactly as nginx does in the image.
const api = process.env.API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: { "/api": { target: api, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") } },
  },
  build: { sourcemap: true, target: "es2023" },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.*", "src/test/**", "src/api/schema.d.ts", "src/main.tsx"],
      // The functional core (reducers, selectors, the stream's state machine) is
      // where correctness lives: it must stay almost fully covered.
      thresholds: {
        "src/chat/transcript.ts": { lines: 90, branches: 90 },
        "src/stream/connection.ts": { lines: 90, branches: 90 },
      },
    },
  },
});
