// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { restoreDialogFocus } from "@/components/contextdb/dialog-focus";
afterEach(() => document.body.replaceChildren());
it("uses a live fallback when a row trigger is removed or disabled", () => {
  const trigger = document.createElement("button");
  const fallback = document.createElement("button");
  document.body.append(trigger, fallback);
  trigger.remove();
  restoreDialogFocus(new Event("close", { cancelable: true }), trigger, fallback);
  expect(document.activeElement).toBe(fallback);
  document.body.append(trigger);
  trigger.disabled = true;
  restoreDialogFocus(new Event("close"), trigger, fallback);
  expect(document.activeElement).toBe(fallback);
});
it("does not steal focus from a replacement dialog or a disconnected page", () => {
  const trigger = document.createElement("button");
  const dialog = document.createElement("div");
  dialog.setAttribute("role", "dialog");
  const input = document.createElement("input");
  dialog.append(input);
  document.body.append(trigger, dialog);
  input.focus();
  restoreDialogFocus(new Event("close"), trigger);
  expect(document.activeElement).toBe(input);
  dialog.remove();
  trigger.remove();
  restoreDialogFocus(new Event("close"), trigger);
  expect(document.activeElement).toBe(document.body);
});
