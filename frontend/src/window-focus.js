import { isCompact } from './device.js';
/**
 * Keyboard focus for desktop windows (FE-11).
 *
 * - Opening or restoring a window moves focus into it; minimizing or closing it returns
 *   focus to whatever had it before (or the dock).
 * - Esc closes the top window, unless focus is in a text field, a terminal or a VM
 *   console (those need Esc themselves) or a dialog is open.
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

  // Remember which window was on top when Esc went down; if another handler closes
  // something for this key press, we don't also close the window underneath.
  let escTop = null;
  document.addEventListener(
    'keydown',
    (e) => {
      if (e.key === 'Escape') escTop = topWindowId(dock);
    },
    true
  );
  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented) return;
    const t = e.target instanceof Element ? e.target : null;
    if (e.key === 'Escape') {
      if (t && (t.matches('input, textarea, select, [contenteditable="true"]') || t.closest(KEEP_ESCAPE))) return;
      if (Array.from(document.querySelectorAll(DIALOGS)).some(visible)) return;
      const id = topWindowId(dock);
      if (!id || id !== escTop) return;
      e.preventDefault();
      if (typeof dock.closeWindow === 'function') dock.closeWindow(id);
      else dock.minimize(id);
    } else if (e.key === '`' && e.altKey) {
      const open = Object.entries(dock.windows || {}).filter(([, w]) => !w.minimized && !w.closed && visible(winOf(w)));
      if (open.length < 2) return;
      e.preventDefault();
      open.sort((a, b) => (parseInt(getComputedStyle(winOf(a[1])).zIndex, 10) || 0) - (parseInt(getComputedStyle(winOf(b[1])).zIndex, 10) || 0));
      dock.restore(open[0][0]); // the one at the back comes to the front
    }
  });
}
