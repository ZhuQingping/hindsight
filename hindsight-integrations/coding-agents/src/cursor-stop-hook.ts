#!/usr/bin/env node
/** contextbase Cursor CLI `stop` hook: retain the completed agent-turn transcript. */
import { runHarnessRetain } from "./harness/hook-lifecycle";

void runHarnessRetain("cursor-cli");
