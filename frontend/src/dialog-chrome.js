/**
 * Gives every pop-up window the same frame as the regular windows: a title bar that drags the
 * window, and the minimize, maximize and close buttons.
 *
 * It covers the `.smart-modal-window` pop-ups (built into the page or created in code) and
 * anything marked `data-dialog-chrome`. Buttons a pop-up already has are left as they are;
 * missing ones are added and handled here. `data-dialog-chrome="alert"` (confirmations and
 * prompts) gets the title bar and close button only, since a pending question should not
 * be tucked away in the dock.
 */
import { DockManager, makeDraggable } from './components/dock.js';
import { t } from './i18n.js';

const WINDOW_SEL = '.smart-modal-window, [data-dialog-chrome]';
const HEADER_SEL = '[data-dialog-header], .smart-modal-header';
const CLOSE_SEL = '.win-btn.close-btn, .close-btn, .modal-close-btn, .modal-close, [data-close]';
// What hides and shows a pop-up as a whole: a dimmed backdrop, or a see-through layer for
// pop-ups that leave the rest of the page usable
const HOST_SEL = '.smart-modal-backdrop, .dlg-modeless';
const GLYPH_CLOSE = /^[×✕✖✗xX]$/;
// Windows that have their own frame
const SKIP_SEL = '.os-window, .chassis-front-panel, .mgmt-app-window';

let _seq = 0;

function isAlert(win) {
  return win.dataset.dialogChrome === 'alert';
}

/** The element shown and hidden as a whole: the backdrop when there is one. */
export function dialogHost(win) {
  return win.closest(HOST_SEL) || win;
}

function findHeader(win) {
  const direct = Array.from(win.children).find((c) => c.matches(HEADER_SEL));
  return direct || win.querySelector(HEADER_SEL);
}

function findClose(header) {
  const marked = header.querySelector(CLOSE_SEL);
  if (marked) return marked;
  return Array.from(header.querySelectorAll('button')).find((b) =>
    GLYPH_CLOSE.test((b.textContent || '').trim())
    || /close/i.test(b.getAttribute('aria-label') || '')
    || /close/i.test(b.title || '')) || null;
}

function makeButton(kind, label) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = `win-btn ${kind}-btn`;
  b.title = label;
  b.setAttribute('aria-label', label);
  b.dataset.chrome = kind;
  return b;
}

function titleOf(win, header) {
  const el = header.querySelector('.smart-modal-title, [id$="-title"], h2, h3') || header;
  return (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60) || 'Window';
}

function iconOf(win, header) {
  if (win.dataset.dockIcon) return win.dataset.dockIcon;
  const use = header.querySelector('use[href^="#i-"]');
  return use ? use.getAttribute('href') : '#i-grid';
}

/** Adds the title-bar buttons and drag handle to one pop-up window. Safe to call again. */
export function upgradeDialog(win) {
  if (!win || win.matches(SKIP_SEL) || win.closest('#console-modal-overlay')) return false;
  const header = findHeader(win);
  // The mark sits on the title bar: some pop-ups re-create it each time they open
  if (!header || header.dataset.chromeReady === '1') return false;
  header.dataset.chromeReady = '1';
  header.classList.add('dialog-chrome-header');

  let controls = header.querySelector('.os-window-controls');
  let close = (controls && controls.querySelector('.close-btn')) || findClose(header);
  if (!controls) {
    controls = document.createElement('div');
    controls.className = 'os-window-controls';
    if (close) close.replaceWith(controls); // keep the buttons where the close button was
    else header.appendChild(controls);
  }
  if (close && close.parentElement !== controls) controls.appendChild(close);
  if (close && !close.classList.contains('win-btn')) {
    if (GLYPH_CLOSE.test((close.textContent || '').trim())) close.textContent = '';
    close.removeAttribute('style');
    close.classList.add('win-btn', 'close-btn');
  }
  if (!close) {
    close = makeButton('close', t('common.close', 'Close'));
    controls.appendChild(close);
  }
  if (!close.getAttribute('aria-label')) close.setAttribute('aria-label', t('common.close', 'Close'));
  if (!close.title) close.title = t('common.close', 'Close');

  const has = (kind) => header.querySelector(`.win-btn.${kind}-btn`);
  if (!isAlert(win)) {
    if (!has('max')) controls.insertBefore(makeButton('max', 'Maximize'), close);
    // Minimizing parks the pop-up in the dock, which needs a backdrop to hide and show
    if (!has('min') && win.closest(HOST_SEL)) {
      controls.insertBefore(makeButton('min', 'Minimize'), controls.querySelector('.max-btn') || close);
    }
  }

  // Drag: set up on the first press so a module's own makeDraggable call (with its window id)
  // runs first when it has one. A capture listener on the window runs before the header's own.
  if (!win._chromeDragHook) {
    win._chromeDragHook = true;
    win.addEventListener('pointerdown', (e) => {
      const h = findHeader(win);
      if (!h || !h.contains(e.target)) return;
      // Our drag handle was replaced along with the title bar: move it to the new one
      if (win._draggableInitialized && win._chromeDragHeader && win._chromeDragHeader !== h) win._cleanupDraggable?.();
      if (win._draggableInitialized) return;
      makeDraggable(win, h);
      win._chromeDragHeader = h;
    }, true);
  }
  return true;
}

function closeDialog(win) {
  const btn = win.querySelector('.os-window-controls .close-btn');
  if (btn && btn.dataset.chrome !== 'close') {
    btn.click();
    return;
  }
  const host = dialogHost(win);
  host.classList.remove('open');
  host.style.display = 'none';
}

/** Maximize and restore, like the File Explorer's maximize. */
export function toggleDialogMaximize(win) {
  if (win.dataset.chromeMax === '1') {
    win.style.cssText = win._chromePreMax || '';
    delete win.dataset.chromeMax;
    return false;
  }
  win._chromePreMax = win.style.cssText;
  Object.assign(win.style, {
    position: 'fixed',
    left: '16px',
    top: '56px',
    right: 'auto',
    bottom: 'auto',
    width: 'calc(100vw - 32px)',
    height: 'calc(100vh - 128px)',
    maxWidth: 'none',
    maxHeight: 'none',
    margin: '0',
    transform: 'none',
  });
  win.dataset.chromeMax = '1';
  return true;
}

// Pop-ups minimized to the dock: dock id -> { host, win, observer }
const _parked = new Map();

function cleanHost(host, win) {
  for (const el of [host, win]) {
    el.classList.remove('window-minimized');
    if (el.style.getPropertyPriority('display') === 'important') el.style.removeProperty('display');
  }
}

function forget(id) {
  const rec = _parked.get(id);
  if (!rec) return;
  _parked.delete(id);
  rec.observer.disconnect();
  if (DockManager.windows[id]) {
    delete DockManager.windows[id];
    if (DockManager.activeId === id) DockManager.activeId = null;
    DockManager.render();
  }
  cleanHost(rec.host, rec.win);
}

function syncParked(id) {
  const rec = _parked.get(id);
  const entry = DockManager.windows[id];
  if (!rec) return;
  if (!entry || !rec.host.isConnected) {
    forget(id);
    return;
  }
  const shown = rec.host.classList.contains('open');
  if (entry.minimized && shown) {
    DockManager.restore(id); // the pop-up's own code opened it again
  } else if (!entry.minimized && !shown) {
    forget(id); // the pop-up closed itself
  }
}

/** Hides a pop-up into the dock; clicking its dock icon brings it back. */
export function minimizeDialog(win) {
  const host = dialogHost(win);
  const known = Object.keys(DockManager.windows).find((k) => DockManager.windows[k].el === host);
  if (known) {
    DockManager.minimize(known);
    return known;
  }
  const header = findHeader(win);
  const id = `dlg-${host.id || ++_seq}`;
  DockManager.register(id, host, iconOf(win, header), titleOf(win, header));
  Object.assign(DockManager.windows[id], {
    transient: true,
    onClose: () => {
      closeDialog(win);
      forget(id);
    },
  });
  const observer = new MutationObserver(() => syncParked(id));
  observer.observe(host, { attributes: true, attributeFilter: ['class', 'style'] });
  _parked.set(id, { host, win, observer });
  DockManager.minimize(id);
  return id;
}

function onControlClick(e) {
  const btn = e.target instanceof Element ? e.target.closest('button[data-chrome]') : null;
  if (!btn) return;
  const win = btn.closest(WINDOW_SEL);
  if (!win) return;
  e.preventDefault();
  e.stopPropagation();
  if (btn.dataset.chrome === 'min') minimizeDialog(win);
  else if (btn.dataset.chrome === 'max') toggleDialogMaximize(win);
  else closeDialog(win);
}

let _scanQueued = false;
function scan() {
  _scanQueued = false;
  for (const win of document.querySelectorAll(WINDOW_SEL)) upgradeDialog(win);
  for (const id of Array.from(_parked.keys())) syncParked(id);
}

function queueScan() {
  if (_scanQueued) return;
  _scanQueued = true;
  (window.requestAnimationFrame || ((fn) => setTimeout(fn, 16)))(scan);
}

let _installed = false;
/** Upgrades the pop-ups on the page now and any that appear later. */
export function installDialogChrome() {
  if (_installed || typeof document === 'undefined') return;
  _installed = true;
  document.addEventListener('click', onControlClick, true);
  scan();
  // Only schedules one cheap pass per frame; the pass looks at the pop-ups, not the whole page.
  new MutationObserver(queueScan).observe(document.body, { childList: true, subtree: true });
}

export const _test = { scan, forget, parked: _parked };
