import { fireEvent, screen } from "@testing-library/react";
import catalogs from "@/i18n/contextdb-catalogs.json";

/** Exercise the real Radix control; JSDOM has no layout scrolling. */
export function selectOption(trigger: HTMLElement, value: string) {
  if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {};
  const labels: Record<string, string> = {
    all: catalogs.en.allSpaces,
    selected: catalogs.en.selectedSpaces,
    read: catalogs.en.readOnly,
    read_write: catalogs.en.readWrite,
  };
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.click(screen.getByRole("option", { name: labels[value] }));
}
