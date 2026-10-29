/**
 * ZettNAS Toolkit Accessibility (A11y) Engine
 * - Attaches keyboard listeners (Enter/Space) to interactive elements
 * - Gives interactive non-semantic elements role="button" and tabindex="0"
 * - Names icon-only ones from their translated title; it never guesses from text and never
 *   hides an interactive element with aria-hidden (FE-10)
 */
import { addedNodes, watchDom } from './dom-watch.js';

export function enhanceInteractiveElements(root) {
  if (!root || !root.querySelectorAll) return;

  const selectors = [
    '.card',
    '.disk',
    '.os-dock-item',
    '.chassis-desktop-icon',
    '.window-control-btn',
    '.win-btn',
    '.snap-slot',
    '.mgmt-tab',
    '.mgmt-card',
    '.mgmt-action-btn',
    '.cal-month-nav',
    '.weather-city-item',
    '.fm-col-name',
    '.fm-col-size',
    '.fm-col-type',
    '[data-action]'
  ];

  const matched = root.matches && selectors.some((s) => root.matches(s)) ? [root] : [];
  const children = Array.from(root.querySelectorAll(selectors.join(',')));
  const elements = matched.concat(children);

  elements.forEach((el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'button' || tag === 'a' || tag === 'input' || tag === 'select' || tag === 'textarea') {
      return;
    }

    if (!el.hasAttribute('role')) {
      el.setAttribute('role', 'button');
    }
    if (!el.hasAttribute('tabindex')) {
      el.setAttribute('tabindex', '0');
    }
    // Name it only when it has no visible text: from its (translated) title, an image's alt
    // text or an SVG <title>. Never hide an interactive element from screen readers (FE-10).
    if (!el.hasAttribute('aria-label') && !el.hasAttribute('aria-labelledby') && !(el.textContent || '').trim()) {
      const img = el.querySelector && el.querySelector('img[alt], svg title');
      const label =
        el.getAttribute('title') ||
        el.getAttribute('data-title') ||
        (img && (img.getAttribute('alt') || img.textContent)) ||
        '';
      if (label.trim()) {
        el.setAttribute('aria-label', label.trim().slice(0, 80));
      } else if (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.DEV) {
        console.warn('[a11y] interactive element without a name:', el);
      }
    }
  });
}

export function initA11yAnnouncer() {
  if (typeof document === 'undefined') return;
  let announcer = document.getElementById('a11y-live-announcer');
  if (!announcer && document.body) {
    announcer = document.createElement('div');
    announcer.id = 'a11y-live-announcer';
    announcer.className = 'sr-only';
    announcer.setAttribute('aria-live', 'polite');
    announcer.setAttribute('aria-atomic', 'true');
    announcer.style.cssText = 'position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); border:0;';
    document.body.appendChild(announcer);
  }
}

export function announceA11y(message) {
  if (typeof document === 'undefined' || !message) return;
  let announcer = document.getElementById('a11y-live-announcer');
  if (!announcer) {
    initA11yAnnouncer();
    announcer = document.getElementById('a11y-live-announcer');
  }
  if (announcer) {
    announcer.textContent = '';
    setTimeout(() => {
      announcer.textContent = message;
    }, 20);
  }
}

const _lastSaid = new Map();

/**
 * UX-28: a region that re-renders on a timer says its summary only when it changes: not when
 * it first appears, and not again while it stays the same.
 */
export function announceChange(key, text) {
  const said = _lastSaid.get(key);
  _lastSaid.set(key, text);
  if (said !== undefined && said !== text && text) announceA11y(text);
}

if (typeof window !== 'undefined') {
  window.announceA11y = announceA11y;
}

const MENU_SEL = '[role="menu"], .context-menu, [id$="context-menu"], [id$="ctx-menu"]';

/** Shift+F10 or the Menu key: the focused element's context menu, then focus into it (UX-29). */
export function onMenuKey(e) {
  const isMenuKey = e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey);
  if (!isMenuKey) return;
  const el = document.activeElement && document.activeElement !== document.documentElement ? document.activeElement : document.body;
  if (el.closest && el.closest('input, textarea, select, [contenteditable="true"]')) return; // the browser's own menu
  e.preventDefault();
  const r = el.getBoundingClientRect ? el.getBoundingClientRect() : { left: 0, top: 0, width: 0, height: 0 };
  el.dispatchEvent(new MouseEvent('contextmenu', {
    bubbles: true,
    cancelable: true,
    clientX: Math.round(r.left + Math.min(r.width / 2, 24)),
    clientY: Math.round(r.top + Math.min(r.height / 2, 12)),
  }));
  requestAnimationFrame(() => {
    const menus = Array.from(document.querySelectorAll(MENU_SEL)).filter((m) => m.style.display !== 'none' && !m.hidden && m.getClientRects().length);
    const first = menus[menus.length - 1]?.querySelector('[role="menuitem"], .context-menu-item, button, [tabindex]');
    if (first) {
      if (!first.hasAttribute('tabindex') && !/^(BUTTON|A)$/.test(first.tagName)) first.setAttribute('tabindex', '-1');
      first.focus();
    }
  });
}

export function initA11y() {
  if (typeof document === 'undefined') return;
  document.addEventListener('keydown', onMenuKey);

  // Global keyboard activation for role="button" and interactive non-semantic elements
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const target = e.target;
    if (!target || !(target instanceof HTMLElement)) return;

    const tag = target.tagName.toLowerCase();
    if (tag === 'button' || tag === 'input' || tag === 'textarea' || tag === 'select' || tag === 'a') {
      return;
    }
    // data-action elements are dom-actions.js's: one activation path, so Enter fires once (UX-31)
    if (target.hasAttribute('data-action')) return;

    if (
      target.getAttribute('role') === 'button' ||
      target.classList.contains('interactive') ||
      target.classList.contains('card') ||
      target.classList.contains('disk') ||
      target.classList.contains('os-dock-item') ||
      target.classList.contains('chassis-desktop-icon') ||
      target.classList.contains('mgmt-tab') ||
      target.classList.contains('mgmt-card') ||
      target.classList.contains('window-control-btn')
    ) {
      e.preventDefault();
      target.click();
    }
  });

  // Observe and auto-enhance interactive elements added to the DOM
  if (document.body) {
    initA11yAnnouncer();
    enhanceInteractiveElements(document.body);

    watchDom({
      onRecords: (records) => {
        for (const node of addedNodes(records)) {
          if (node instanceof HTMLElement) enhanceInteractiveElements(node);
        }
      },
    });
  }
}
