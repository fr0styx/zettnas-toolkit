// FE-04: Mission Control's markup is about half of the page, so it isn't in index.html.
// It's inserted the first time it's needed: when Mission Control opens, when other code
// asks for it, or when the browser is idle a few seconds after start.
import { applyTranslations } from './i18n.js';
import { ZettEventBus } from './event-bus.js';

const waiters = [];
let pending = null;

export function isManagementDomReady() {
  return !!document.getElementById('management-modal-overlay');
}

/** Runs fn once Mission Control's markup is in the page (now, if it already is). */
export function onManagementDom(fn) {
  if (isManagementDomReady()) fn();
  else waiters.push(fn);
}

export function ensureManagementDom() {
  if (isManagementDomReady()) return Promise.resolve();
  if (!pending) {
    pending = import('./windows/management-window.html?raw').then(({ default: markup }) => {
      if (!isManagementDomReady()) {
        const slot = document.getElementById('management-window-slot');
        if (slot) slot.insertAdjacentHTML('beforebegin', markup);
        else document.body.insertAdjacentHTML('beforeend', markup);
        slot?.remove();
      }
      applyTranslations();
      for (const fn of waiters.splice(0)) {
        try {
          fn();
        } catch (err) {
          console.error('Mission Control setup failed:', err);
        }
      }
      ZettEventBus.emit('dom:management-ready');
    });
  }
  return pending;
}
