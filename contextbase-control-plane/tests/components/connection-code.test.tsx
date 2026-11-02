// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { toast } from "sonner";
import { ConnectionCode } from "@/components/connection-code";
import messages from "@/messages/en.json";

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const execCommandDescriptor = Object.getOwnPropertyDescriptor(document, "execCommand");
const code = "export CONTEXTBASE_API_URL='http://example.test:8888'\ncommand --bank-id 'team'";

function setClipboard(value: Pick<Clipboard, "writeText"> | undefined) {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value });
}

function setLegacyCopy(copy: () => boolean) {
  const fn = vi.fn(copy);
  Object.defineProperty(document, "execCommand", { configurable: true, value: fn });
  return fn;
}

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <ConnectionCode code={code} />
    </NextIntlClientProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  if (clipboardDescriptor) Object.defineProperty(navigator, "clipboard", clipboardDescriptor);
  else Reflect.deleteProperty(navigator, "clipboard");
  if (execCommandDescriptor) Object.defineProperty(document, "execCommand", execCommandDescriptor);
  else Reflect.deleteProperty(document, "execCommand");
});

it("uses Clipboard API when available", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  setClipboard({ writeText });
  const legacyCopy = setLegacyCopy(() => true);
  show();
  fireEvent.click(screen.getByRole("button", { name: messages.common.copy }));
  await screen.findByRole("button", { name: messages.common.copied });
  expect(writeText).toHaveBeenCalledWith(code);
  expect(legacyCopy).not.toHaveBeenCalled();
  expect(toast.error).not.toHaveBeenCalled();
});

it("copies multiline commands when Clipboard API is absent on HTTP origins", async () => {
  setClipboard(undefined);
  const legacyCopy = setLegacyCopy(() => {
    const textarea = document.activeElement;
    expect(textarea).toBeInstanceOf(HTMLTextAreaElement);
    expect((textarea as HTMLTextAreaElement).value).toBe(code);
    expect((textarea as HTMLTextAreaElement).readOnly).toBe(true);
    expect((textarea as HTMLTextAreaElement).selectionStart).toBe(0);
    expect((textarea as HTMLTextAreaElement).selectionEnd).toBe(code.length);
    return true;
  });
  show();
  const button = screen.getByRole("button", { name: messages.common.copy });
  button.focus();
  fireEvent.click(button);
  await screen.findByRole("button", { name: messages.common.copied });
  expect(legacyCopy).toHaveBeenCalledWith("copy");
  expect(document.querySelector("textarea")).toBeNull();
  expect(document.activeElement).toBe(button);
  expect(toast.error).not.toHaveBeenCalled();
});

it("falls back when Clipboard API rejects permission", async () => {
  setClipboard({ writeText: vi.fn().mockRejectedValue(new Error("NotAllowedError")) });
  const legacyCopy = setLegacyCopy(() => true);
  show();
  fireEvent.click(screen.getByRole("button", { name: messages.common.copy }));
  await screen.findByRole("button", { name: messages.common.copied });
  expect(legacyCopy).toHaveBeenCalledWith("copy");
  expect(document.querySelector("textarea")).toBeNull();
  expect(toast.error).not.toHaveBeenCalled();
});

it.each(["false", "throw", "missing"] as const)(
  "offers manual copying and cleans up when legacy copy returns %s",
  async (failure) => {
    setClipboard(undefined);
    if (failure === "missing") {
      Object.defineProperty(document, "execCommand", { configurable: true, value: undefined });
    } else {
      setLegacyCopy(() => {
        if (failure === "throw") throw new Error("Copy blocked");
        return false;
      });
    }
    show();
    const button = screen.getByRole("button", { name: messages.common.copy });
    button.focus();
    fireEvent.click(button);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(messages.common.copyFailed));
    expect(screen.queryByRole("button", { name: messages.common.copied })).toBeNull();
    expect(document.querySelector("textarea")).toBeNull();
    expect(document.activeElement).toBe(button);
  }
);

it("clears a previous success when both clipboard paths fail on a later attempt", async () => {
  const writeText = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValue(new Error("Denied"));
  setClipboard({ writeText });
  setLegacyCopy(() => false);
  show();
  fireEvent.click(screen.getByRole("button", { name: messages.common.copy }));
  const button = await screen.findByRole("button", { name: messages.common.copied });
  fireEvent.click(button);
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith(messages.common.copyFailed));
  expect(screen.getByRole("button", { name: messages.common.copy })).toBeTruthy();
});
