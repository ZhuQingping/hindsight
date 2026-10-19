import { defineConfig } from "vitest/config";
import { tmpdir } from "node:os";
import { join } from "node:path";

export default defineConfig({
  test: {
    env: {
      // Unit tests exercise code paths that emit diagnostics; keep them out of the REAL
      // ~/.contextbase/coding-agents-logs so a developer's trail isn't polluted with test noise.
      CONTEXTBASE_DIAG_FILE: join(tmpdir(), "contextbase-plugin-test.log"),
      CONTEXTBASE_LOG_FILE: join(tmpdir(), "contextbase-plugin-test-leveled.log"),
      CONTEXTBASE_USAGE_FILE: join(tmpdir(), "contextbase-plugin-test-usage.jsonl"),
      // Same reasoning for the CONFIG file: `loadConfig` otherwise resolves the developer's real
      // ~/.contextbase/coding-agent.json, so a machine that has a token (or a bank override, or a
      // different apiUrl) fails assertions that a clean machine passes. It must be set HERE rather
      // than with vi.stubEnv in a test: config.ts captures the path in a module-level constant, so
      // by the time a test body runs the value is already fixed. Points at a path with no file.
      CONTEXTBASE_CONFIG: join(tmpdir(), "contextbase-coding-agent-test-absent.json"),
    },
  },
});
