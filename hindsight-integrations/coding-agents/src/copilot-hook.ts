#!/usr/bin/env node
/** GitHub Copilot CLI userPromptTransformed hook — shared contextbase prompt lifecycle. */
import { runHarnessPrompt } from "./harness/hook-lifecycle";

void runHarnessPrompt("copilot-cli");
