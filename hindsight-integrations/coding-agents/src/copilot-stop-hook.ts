#!/usr/bin/env node
/** GitHub Copilot CLI agentStop hook — shared contextbase transcript retention lifecycle. */
import { runHarnessRetain } from "./harness/hook-lifecycle";

void runHarnessRetain("copilot-cli");
