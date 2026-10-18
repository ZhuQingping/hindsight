import { fireEvent, screen } from "@testing-library/react";

/** Follow the same keyboard menu path as the UI, including its focus owner. */
export async function openMenuAction(trigger: HTMLElement, action: string) {
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "Enter" });
  fireEvent.click(await screen.findByRole("menuitem", { name: action }));
}
