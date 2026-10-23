import DOMPurify from 'dompurify';
import { formatBytes as formatSize } from './format.js';
/**
 * Core UI Utilities
 */

export function isFocusableElementVisible(el) {
  if (!el || el.disabled) return false;
  if (el.getAttribute('aria-hidden') === 'true') return false;
  if (el.hasAttribute('hidden')) return false;
  if (el.style && (el.style.display === 'none' || el.style.visibility === 'hidden')) return false;

  // Filter out elements residing inside hidden containers or inactive tabs
  if (el.closest?.('[aria-hidden="true"], [hidden], .tab-pane:not(.active), .mgmt-tab-pane:not(.active), .mgmt-content-pane:not(.active)')) {
    return false;
  }
  if (el.closest?.('[style*="display: none"], [style*="display:none"], [style*="visibility: hidden"], [style*="visibility:hidden"]')) {
    return false;
  }

  // Modern browser checkVisibility API when available
  if (typeof el.checkVisibility === 'function') {
    try {
      if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) {
        return false;
      }
    } catch (_) {
      if (!el.checkVisibility()) return false;
    }
  }

  // In standard browser engines, elements detached or hidden return null offsetParent
  const isJSDOM = typeof navigator !== 'undefined' && (/jsdom/i.test(navigator.userAgent) || Boolean(window._jsdom));
  if (!isJSDOM && el.offsetParent === null && el.style?.position !== 'fixed') {
    return false;
  }

  return true;
}

export function trapFocus(element, onClose = null) {
  if (!element) return () => {};

  const FOCUSABLE_SELECTOR = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function getFocusableElements() {
    return Array.from(element.querySelectorAll(FOCUSABLE_SELECTOR)).filter(isFocusableElementVisible);
  }

  function onKeyDown(e) {
    if (e.key === 'Escape') {
      if (typeof onClose === 'function') {
        e.preventDefault();
        onClose(e);
      }
      return;
    }

    if (e.key !== 'Tab') return;

    const focusable = getFocusableElements();
    if (!focusable.length) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === first || !element.contains(document.activeElement)) {
        last.focus();
        e.preventDefault();
      }
    } else {
      if (document.activeElement === last || !element.contains(document.activeElement)) {
        first.focus();
        e.preventDefault();
      }
    }
  }

  element.addEventListener('keydown', onKeyDown);
  return () => element.removeEventListener('keydown', onKeyDown);
}

export function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Toasts and confirm dialogs render a little formatting (bold, code, lists, links).
// DOMPurify does the cleaning (FE-09); the regex filter it replaces could be bypassed.
const MODAL_ALLOWED_TAGS = ['strong', 'b', 'em', 'i', 'code', 'br', 'p', 'span', 'small', 'div', 'a', 'ul', 'ol', 'li'];
let _purifyHooked = false;

export function sanitizeModalHtml(html) {
  if (html == null) return '';
  if (!_purifyHooked) {
    _purifyHooked = true;
    DOMPurify.addHook('afterSanitizeAttributes', (node) => {
      const style = node.getAttribute && node.getAttribute('style');
      if (style && /url\s*\(|expression|javascript:/i.test(style)) node.removeAttribute('style');
      if (node.tagName === 'A' && node.getAttribute('href')) {
        node.setAttribute('target', '_blank');
        node.setAttribute('rel', 'noopener noreferrer');
      }
    });
  }
  return DOMPurify.sanitize(String(html), {
    ALLOWED_TAGS: MODAL_ALLOWED_TAGS,
    ALLOWED_ATTR: ['style', 'class', 'href', 'target', 'rel', 'title'],
    ALLOW_DATA_ATTR: false,
    ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|\/|#)/i,
  });
}

export async function copyTextToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return true;
  }
  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.style.position = 'fixed';
  textArea.style.left = '-999999px';
  textArea.style.top = '-999999px';
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  let success = false;
  try {
    success = document.execCommand('copy');
  } catch (err) {
    console.error('Fallback clipboard copy failed:', err);
  }
  textArea.remove();
  return success;
}

/**
 * Copies text, also on plain HTTP where the browser hides navigator.clipboard
 * (a NAS is often opened as http://<ip>). Throws when nothing was copied.
 */
export async function copyText(text) {
  if (!(await copyTextToClipboard(String(text ?? '')))) throw new Error('Copy failed');
}

export function formatBytes(bytes, decimals = 1) {
  return formatSize(bytes, { decimals: decimals < 0 ? 0 : decimals });
}

/**
 * Perform high-performance DOM reconciliation for dynamic table rows or lists.
 * Reuses existing DOM nodes by key, updates their contents, and pre-prunes stale nodes
 * to prevent layout thrashing and preserve selection / focus state.
 *
 * @param {HTMLElement} parentEl - The container element (tbody, ul, div)
 * @param {Array<Object>} items - The incoming dataset array
 * @param {Function} keyFn - Function returning a unique string key for an item
 * @param {Function} createRowFn - Function returning a newly created HTMLElement for an item
 * @param {Function} [updateRowFn] - Function updating an existing HTMLElement with the new item data
 */
export function reconcileKeyedTable(parentEl, items, keyFn, createRowFn, updateRowFn) {
  if (!parentEl || !Array.isArray(items)) return;

  const incomingKeys = new Set(items.map(item => String(keyFn(item))));
  const existingMap = new Map();
  const children = parentEl.children;

  // 1. Pre-prune stale nodes before insertion to eliminate cascading shift mutations
  for (let i = children.length - 1; i >= 0; i--) {
    const child = children[i];
    const key = child.dataset?.key ?? child.dataset?.dev ?? child.dataset?.id;
    if (key != null) {
      const keyStr = String(key);
      if (!incomingKeys.has(keyStr)) {
        child.remove();
      } else {
        existingMap.set(keyStr, child);
      }
    } else {
      // Untracked placeholder child (e.g. empty state row)
      child.remove();
    }
  }

  // 2. Iterate and re-order / insert / update rows with position accuracy
  const itemsCount = items.length;
  for (let index = 0; index < itemsCount; index++) {
    const item = items[index];
    const key = String(keyFn(item));
    let row = existingMap.get(key);

    if (row) {
      if (updateRowFn) updateRowFn(row, item);
    } else {
      row = createRowFn(item);
      if (row) {
        row.dataset.key = key;
      }
    }

    if (row) {
      const currentChild = children[index];
      if (currentChild !== row) {
        parentEl.insertBefore(row, currentChild || null);
      }
    }
  }
}
