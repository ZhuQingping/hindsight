/** Restore a controlled management dialog to its owner, without stealing a new dialog's focus. */
export function restoreDialogFocus(
  event: Event,
  trigger: HTMLElement | null,
  fallback?: HTMLElement | null
) {
  event.preventDefault();
  const activeDialog = document.activeElement?.closest('[role="dialog"]');
  if (activeDialog && activeDialog !== event.target) return;
  const target = [trigger, fallback].find(
    (element) => element?.isConnected && !element.matches(":disabled")
  );
  target?.focus();
}
