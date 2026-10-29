import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  resolve: {
    alias: {
      // Next enforces this marker in production; Vitest runs server handlers in Node.
      "server-only": fileURLToPath(
        new URL("../node_modules/next/dist/compiled/server-only/empty.js", import.meta.url)
      ),
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    // Transform next-intl's extensionless next/server import for real middleware tests.
    server: { deps: { inline: ["next-intl"] } },
    globals: true,
    environment: "node",
    include: [
      "tests/**/*.test.ts",
      "tests/**/*.test.tsx",
      "src/**/*.test.ts",
      "src/**/*.test.tsx",
      "../hindsight-extensions/contextdb-service/tests/ui/**/*.test.{ts,tsx}",
    ],
  },
});
