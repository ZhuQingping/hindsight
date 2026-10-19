#!/usr/bin/env node
/** agentstratum Qwen Code `Stop` hook: retain the completed agent-turn transcript. */
import { runHarnessRetain } from "./harness/hook-lifecycle";

void runHarnessRetain("qwen-code");
