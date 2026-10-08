/**
 * ZettNAS Toolkit Accessibility (A11y) Engine
 * - Attaches keyboard listeners (Enter/Space) to interactive elements
 * - Ensures role="button", tabindex="0", and aria-label are present on interactive non-semantic elements
 */

export function enhanceInteractiveElements(root) {
  if (!root || !root.querySelectorAll) return;

  const selectors = [
    '.card',
    '.disk',
    '.os-dock-item',
    '.chassis-desktop-icon',
    '.window-control-btn',
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
    if (!el.hasAttribute('aria-label') && !el.hasAttribute('title')) {
      const label = el.getAttribute('data-title') ||
                    (el.innerText && el.innerText.trim()) ||
                    (el.getAttribute('data-action') ? el.getAttribute('data-action').replace(/[-_]/g, ' ') : '');
      if (label && label.length > 0) {
        el.setAttribute('aria-label', label.slice(0, 50));
      } else if (!el.children.length && !el.innerText?.trim()) {
        el.setAttribute('aria-hidden', 'true');
      }
    }
  });
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
