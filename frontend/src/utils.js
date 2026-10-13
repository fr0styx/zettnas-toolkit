/**
 * Core UI Utilities
 */

export function trapFocus(element) {
  if (!element) return () => {};
  const focusable = element.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
  if (!focusable.length) return () => {};

  const first = focusable[0];
  const last = focusable[focusable.length - 1];

  function onKeyDown(e) {
    if (e.key !== 'Tab') return;
    if (e.shiftKey) {
      if (document.activeElement === first) {
        last.focus();
        e.preventDefault();
      }
    } else {
      if (document.activeElement === last) {
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

export function formatBytes(bytes, decimals = 1) {
  if (bytes === 0 || !bytes) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
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
