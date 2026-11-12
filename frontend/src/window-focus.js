import { isCompact } from './device.js';
/**
 * Keyboard focus for desktop windows (FE-11).
 *
 * - Opening or restoring a window moves focus into it; minimizing or closing it returns
 *   focus to whatever had it before (or the dock).
 * - Esc closes the top window, unless focus is in a text field, a terminal or a VM
 *   console (those need Esc themselves), a dialog is open, or something else on the page
 *   used the key (a menu or picker closed, focus moved).
 * - Alt+` cycles through open windows.
 */
const FOCUSABLE =
  '[autofocus], input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled]), ' +
  'button:not([disabled]), a[href], area[href], [tabindex]:not([tabindex="-1"])';
const KEEP_ESCAPE = '.xterm, canvas, .vm-console-window, #vm-console-window, [data-keep-escape]';
const DIALOGS = '#confirm-toast-modal, .prompt-toast-modal, [role="dialog"][aria-modal="true"]';

const _openers = new WeakMap();

function visible(el) {
  if (!el || !el.isConnected) return false;
  if (el.classList.contains('window-minimized')) return false;
  const st = typeof getComputedStyle === 'function' ? getComputedStyle(el) : null;
  return !(st && (st.display === 'none' || st.visibility === 'hidden'));
}

/**
 * Whether a dialog is on screen: also false when an ancestor hides it (Spotlight keeps its dialog
 * inside a hidden overlay, and that hidden dialog used to switch Escape off for the whole page).
 */
function shown(el) {
  if (!visible(el)) return false;
  if (typeof el.checkVisibility === 'function') return el.checkVisibility({ visibilityProperty: true });
  for (let up = el.parentElement; up; up = up.parentElement) {
    const st = getComputedStyle(up);
    if (st.display === 'none' || st.visibility === 'hidden') return false;
  }
  return true;
}

/** Changes that mean a handler used the Escape key: something opened, closed, hid or showed. */
const ESC_WATCH = ['class', 'style', 'hidden', 'open', 'aria-hidden', 'aria-expanded'];

/** Whether anything on the page reacted to this Escape: a change in the page or focus moved. */
export function escapeUsed(watch, focusBefore) {
  const changes = watch ? watch.takeRecords() : [];
  if (watch) watch.disconnect();
  return changes.length > 0 || document.activeElement !== focusBefore;
}

function winOf(entry) {
  const el = entry && entry.el;
  if (!el) return null;
  return el.matches('.os-window, .smart-modal-window, .file-manager-window, .mgmt-app-window, .chassis-front-panel')
    ? el
    : el.querySelector('.os-window, .smart-modal-window, .file-manager-window, .mgmt-app-window, .chassis-front-panel') || el;
}

const TITLES = '.os-window-title, .smart-modal-title, .mgmt-window-title, [data-window-title]';

/**
 * UX-7: a desktop window is a region named by its title, and the title is a level-2 heading,
 * so screen readers can list and jump between open windows.
 */
export function labelWindow(win) {
  if (!win || win.dataset.windowLabelled === '1') return;
  const title = win.querySelector(TITLES);
  if (!win.getAttribute('role')) win.setAttribute('role', 'region');
  if (title) {
    if (!title.id) title.id = `${win.id || 'win'}-title-${Math.random().toString(36).slice(2, 7)}`;
    if (!win.getAttribute('aria-labelledby') && !win.getAttribute('aria-label')) win.setAttribute('aria-labelledby', title.id);
    if (!/^H[1-6]$/.test(title.tagName) && !title.getAttribute('role')) {
      title.setAttribute('role', 'heading');
      title.setAttribute('aria-level', '2');
    }
  }
  win.dataset.windowLabelled = '1';
}

/** A desktop window with no place of its own opens centred below the top bar, not under it. */
export function placeIfUnplaced(win) {
  if (!win || !win.classList || !win.classList.contains('os-window') || win.style.top) return;
  if (isCompact()) return;
  const r = win.getBoundingClientRect();
  if (r.top >= 52) return; // already clear of the top bar
  const w = r.width || 900;
  const h = r.height || 600;
  win.style.left = `${Math.max(24, Math.round((window.innerWidth - w) / 2))}px`;
  win.style.top = `${Math.max(56, Math.round((window.innerHeight - h) / 2) - 20)}px`;
}

export function focusWindow(win) {
  if (!win) return;
  const active = document.activeElement;
  if (active && active !== document.body && !win.contains(active)) _openers.set(win, active);
  const body = win.querySelector('.os-window-body, .modal-body, .fm-body') || win;
  const target = Array.from(body.querySelectorAll(FOCUSABLE)).find((el) => visible(el) && !el.closest('.os-window-header'));
  if (target) {
    target.focus({ preventScroll: true });
  } else {
    if (!win.hasAttribute('tabindex')) win.setAttribute('tabindex', '-1');
    win.focus({ preventScroll: true });
  }
}

export function returnFocus(win, dock = null) {
  if (!win) return;
  const active = document.activeElement;
  if (active && active !== document.body && !win.contains(active)) return; // focus already moved on
  const opener = _openers.get(win);
  _openers.delete(win);
  if (opener && opener.isConnected && visible(opener)) {
    opener.focus({ preventScroll: true });
    return;
  }
  // Like a desktop: the window now on top gets focus; the dock only when none is left
  const nextId = dock ? topWindowId(dock) : null;
  const next = nextId ? winOf(dock.windows[nextId]) : null;
  if (next && next !== win) {
    focusWindow(next);
    return;
  }
  const fallback = document.querySelector('#os-dock-container button, #os-dock-container [tabindex="0"]');
  if (fallback) fallback.focus({ preventScroll: true, focusVisible: false });
}

function topWindowId(dock) {
  let best = null;
  let bestZ = -Infinity;
  for (const [id, entry] of Object.entries(dock.windows || {})) {
    if (entry.minimized || entry.closed) continue;
    const win = winOf(entry);
    if (!visible(win)) continue;
    const z = parseInt(getComputedStyle(win).zIndex, 10) || 0;
    if (z >= bestZ) {
      best = id;
      bestZ = z;
    }
  }
  return best;
}

export function installWindowFocus(dock) {
  if (!dock || dock.__focusInstalled) return;
  dock.__focusInstalled = true;
  const later = (fn) => (typeof requestAnimationFrame === 'function' ? requestAnimationFrame(fn) : setTimeout(fn, 0));
  const wrap = (name, after) => {
    const orig = dock[name];
    if (typeof orig !== 'function') return;
    dock[name] = function (id, ...rest) {
      const before = winOf(this.windows?.[id]);
      const result = orig.call(this, id, ...rest);
      after(this, id, before, rest);
      return result;
    };
  };
  wrap('restore', (d, id) => later(() => {
    placeIfUnplaced(winOf(d.windows?.[id]));
    labelWindow(winOf(d.windows?.[id]));
    focusWindow(winOf(d.windows?.[id]));
  }));
  wrap('register', (d, id, before, rest) => {
    later(() => labelWindow(winOf(d.windows?.[id])));
    if (!rest[3]) later(() => focusWindow(winOf(d.windows?.[id])));
  });
  wrap('minimize', (d, id, before) => returnFocus(before, d));
  wrap('unregister', (d, id, before) => returnFocus(before, d));

  // When Esc goes down: remember the top window and start watching the page. About 40 places
  // handle Escape themselves (menus, dialogs, pickers) and few mark the key as handled, so the
  // closer below asks the page instead: if anything reacted to this key, the key was theirs.
  let escTop = null;
  let escFocus = null;
  let escWatch = null;
  document.addEventListener(
    'keydown',
    (e) => {
      if (e.key !== 'Escape') return;
      escTop = topWindowId(dock);
      escFocus = document.activeElement;
      if (escWatch) escWatch.disconnect();
      escWatch = typeof MutationObserver === 'function' ? new MutationObserver(() => {}) : null;
      if (escWatch) escWatch.observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ESC_WATCH });
    },
    true
  );
  // Last of all (on window, after every element's and the document's own handlers): an Esc that
  // nothing used closes the window on top
  window.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const used = escapeUsed(escWatch, escFocus);
    escWatch = null;
    if (e.defaultPrevented || used) return;
    const t = e.target instanceof Element ? e.target : null;
    if (t && (t.matches('input, textarea, select, [contenteditable="true"]') || t.closest(KEEP_ESCAPE))) return;
    // a window that calls itself a dialog (Settings does) is a window: while it was open,
    // Escape closed nothing, Settings included (SET-12)
    const frames = new Set(Object.values(dock.windows || {}).map((w) => w && w.el));
    if (Array.from(document.querySelectorAll(DIALOGS)).some((el) => shown(el) && !frames.has(el))) return;
    const id = topWindowId(dock);
    if (!id || id !== escTop) return;
    e.preventDefault();
    if (typeof dock.closeWindow === 'function') dock.closeWindow(id);
    else dock.minimize(id);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === '`' && e.altKey) {
      const open = Object.entries(dock.windows || {}).filter(([, w]) => !w.minimized && !w.closed && visible(winOf(w)));
      if (open.length < 2) return;
      e.preventDefault();
      open.sort((a, b) => (parseInt(getComputedStyle(winOf(a[1])).zIndex, 10) || 0) - (parseInt(getComputedStyle(winOf(b[1])).zIndex, 10) || 0));
      dock.restore(open[0][0]); // the one at the back comes to the front
    }
  });
}
