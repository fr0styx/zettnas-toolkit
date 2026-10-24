/**
 * Tab rows that screen readers and keyboards understand (UX-9): each tab names the panel it
 * controls, each panel is labelled by its tab, only the selected tab is in the Tab order, and
 * the arrow keys, Home and End move between tabs.
 */
let _seq = 0;

function tabsOf(list) {
  return Array.from(list.querySelectorAll('[role="tab"]')).filter((t) => t.closest('[role="tablist"]') === list);
}

function syncTabStops(list) {
  const tabs = tabsOf(list);
  const selected = tabs.find((t) => t.getAttribute('aria-selected') === 'true') || tabs[0];
  tabs.forEach((t) => t.setAttribute('tabindex', t === selected ? '0' : '-1'));
}

export function wireTablist(list) {
  if (!list || list.dataset.tabA11y === '1') return;
  list.dataset.tabA11y = '1';
  for (const tab of tabsOf(list)) {
    if (!tab.id) tab.id = `zn-tab-${++_seq}`;
    const target = tab.dataset.tabTarget || tab.getAttribute('aria-controls');
    const panel = target ? document.getElementById(target) : null;
    if (panel) {
      tab.setAttribute('aria-controls', panel.id);
      panel.setAttribute('role', 'tabpanel');
      if (!panel.hasAttribute('aria-labelledby')) panel.setAttribute('aria-labelledby', tab.id);
    } else {
      tab.removeAttribute('aria-controls');
    }
  }
  syncTabStops(list);
  list.addEventListener('click', () => setTimeout(() => syncTabStops(list), 0));
  list.addEventListener('keydown', (e) => {
    const tabs = tabsOf(list).filter((t) => !t.disabled && t.offsetParent !== null);
    const i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    let next = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = tabs[(i + 1) % tabs.length];
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = tabs[(i - 1 + tabs.length) % tabs.length];
    else if (e.key === 'Home') next = tabs[0];
    else if (e.key === 'End') next = tabs[tabs.length - 1];
    if (!next) return;
    e.preventDefault();
    next.focus();
    next.click();
  });
}

export function wireTablists(root = document) {
  root.querySelectorAll('[role="tablist"]').forEach(wireTablist);
}

/** Navigation lists mark the current item with aria-current instead of tab roles. */
export function markCurrent(items, isCurrent) {
  items.forEach((el) => {
    if (isCurrent(el)) el.setAttribute('aria-current', 'page');
    else el.removeAttribute('aria-current');
  });
}
