/** Keep keyboard focus inside the active confirmation dialog. */
export function keepDialogFocus(event, dialog, activeElement) {
  if (event.key !== "Tab" || !dialog) return false;

  const focusable = [
    ...dialog.querySelectorAll(
      "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])",
    ),
  ];
  if (focusable.length === 0) {
    event.preventDefault();
    dialog.focus();
    return true;
  }

  const activeIndex = focusable.indexOf(activeElement);
  if (event.shiftKey && activeIndex <= 0) {
    event.preventDefault();
    focusable[focusable.length - 1].focus();
    return true;
  }
  if (!event.shiftKey && (activeIndex === -1 || activeIndex === focusable.length - 1)) {
    event.preventDefault();
    focusable[0].focus();
    return true;
  }
  return false;
}
