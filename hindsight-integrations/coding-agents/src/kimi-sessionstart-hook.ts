#!/usr/bin/env node
/**
 * contextbase Kimi Code `SessionStart` hook.
 *
 * Install (~/.kimi-code/config.toml) — the entry schema is STRICT, exactly these four keys:
 *   [[hooks]]
 *   event = "SessionStart"
 *   command = "contextbase-kimi-sessionstart-hook"
 *   timeout = 30
 * A fifth key drops EVERY hook in the file at warning severity while the CLI still boots.
 */
import { runHarnessSessionStart } from "./harness/hook-lifecycle";

void runHarnessSessionStart("kimi-code");
