/**
 * Loads a window's code the first time it is used, not with the page (FE-02).
 *
 * Until then its desktop icon and global open functions are small stubs. Hovering the
 * icon starts the download; the first click (or call) loads and initialises the module,
 * then forwards to the real function. A window that was open before a reload is
 * restored once its module has loaded.
 */
import { OPEN_WINDOWS_KEY } from './components/dock.js';

const _entries = {};

function wasOpen(id) {
  try {
    const raw = JSON.parse(localStorage.getItem(OPEN_WINDOWS_KEY) || 'null');
    return Boolean(raw && raw.windows && Object.prototype.hasOwnProperty.call(raw.windows, id));
  } catch (e) {
    return false;
  }
}

export function lazyWindow({ id, iconId, load, init, globals = [], openGlobal }) {
  let promise = null;
  const stubs = {};
  const ensure = () => {
    if (!promise) {
      promise = load().then((mod) => {
        mod[init]();
        if (icon) EVENTS.forEach((ev) => icon.removeEventListener(ev, onIcon));
        return mod;
      });
      promise.catch(() => {
        promise = null; // allow a retry, e.g. after a network blip
      });
    }
    return promise;
  };
  globals.forEach((name) => {
    const stub = async (...args) => {
      await ensure();
      if (window[name] && window[name] !== stub) return window[name](...args);
      return undefined;
    };
    stubs[name] = stub;
    window[name] = stub;
  });
  const EVENTS = ['click', 'dblclick', 'touchend', 'keydown'];
  const icon = iconId ? document.getElementById(iconId) : null;
  async function onIcon(e) {
    if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
    if (e.type === 'touchend' || e.type === 'keydown') e.preventDefault();
    await ensure();
    if (openGlobal && typeof window[openGlobal] === 'function') window[openGlobal]();
  }
  if (icon) {
    EVENTS.forEach((ev) => icon.addEventListener(ev, onIcon));
    icon.addEventListener('pointerenter', () => ensure(), { once: true });
  }
  if (id && wasOpen(id)) {
    ensure().then(() => openGlobal && window[openGlobal] && window[openGlobal]());
  }
  _entries[id || iconId] = { ensure };
  return ensure;
}

export function _lazyEntriesForTesting() {
  return _entries;
}
