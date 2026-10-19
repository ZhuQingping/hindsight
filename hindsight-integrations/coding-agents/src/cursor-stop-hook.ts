#!/usr/bin/env node
/** agentstratum Cursor CLI `stop` hook: retain the completed agent-turn transcript. */
import { runHarnessRetain } from "./harness/hook-lifecycle";

void runHarnessRetain("cursor-cli");
