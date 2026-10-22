/**
 * ZettNAS Toolkit Accessibility (A11y) Engine
 * - Attaches keyboard listeners (Enter/Space) to interactive elements
 * - Gives interactive non-semantic elements role="button" and tabindex="0"
 * - Names icon-only ones from their translated title; it never guesses from text and never
 *   hides an interactive element with aria-hidden (FE-10)
 */

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

if (typeof window !== 'undefined') {
  window.announceA11y = announceA11y;
}

export function initA11y() {
  if (typeof document === 'undefined') return;

  // Global keyboard activation for role="button" and interactive non-semantic elements
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const target = e.target;
    if (!target || !(target instanceof HTMLElement)) return;

    const tag = target.tagName.toLowerCase();
    if (tag === 'button' || tag === 'input' || tag === 'textarea' || tag === 'select' || tag === 'a') {
      return;
    }

    if (
      target.getAttribute('role') === 'button' ||
      target.classList.contains('interactive') ||
      target.classList.contains('card') ||
      target.classList.contains('disk') ||
      target.classList.contains('os-dock-item') ||
      target.classList.contains('chassis-desktop-icon') ||
      target.classList.contains('mgmt-tab') ||
      target.classList.contains('mgmt-card') ||
      target.classList.contains('window-control-btn') ||
      target.hasAttribute('data-action')
    ) {
      e.preventDefault();
      target.click();
    }
  });

  // Observe and auto-enhance interactive elements added to the DOM
  if (document.body) {
    initA11yAnnouncer();
    enhanceInteractiveElements(document.body);

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node instanceof HTMLElement) {
            enhanceInteractiveElements(node);
          }
        }
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }
}
