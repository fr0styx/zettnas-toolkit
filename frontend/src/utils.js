/**
 * Utility functions for HTML sanitization and UI helpers.
 */

export function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export function sanitizeText(str) {
  return escapeHtml(str);
}

/**
 * Traps keyboard focus within a container element for accessibility (a11y).
 * Handles Tab, Shift+Tab cycling, and optional Escape key dismissal.
 * Returns an unbind cleanup function.
 */
export function trapFocus(element, onEscape = null) {
  if (!element) return () => {};

  const focusableSelector =
    'button:not([disabled]):not([tabindex="-1"]), [href]:not([tabindex="-1"]), input:not([disabled]):not([tabindex="-1"]), select:not([disabled]):not([tabindex="-1"]), textarea:not([disabled]):not([tabindex="-1"]), [tabindex]:not([tabindex="-1"])';

  function handleKeyDown(e) {
    if (e.key === 'Escape' && onEscape) {
      e.preventDefault();
      onEscape();
      return;
    }
    if (e.key !== 'Tab') return;

    const focusables = Array.from(element.querySelectorAll(focusableSelector)).filter(
      (el) => el.offsetParent !== null || el.offsetWidth > 0 || el.offsetHeight > 0
    );
    if (focusables.length === 0) return;

    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === first || !element.contains(document.activeElement)) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last || !element.contains(document.activeElement)) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  element.addEventListener('keydown', handleKeyDown);

  // Auto-focus first focusable element inside the modal
  setTimeout(() => {
    const first = element.querySelector(focusableSelector);
    if (first && !element.contains(document.activeElement)) {
      first.focus();
    }
  }, 60);

  return () => {
    element.removeEventListener('keydown', handleKeyDown);
  };
}
