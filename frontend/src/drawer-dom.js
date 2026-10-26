// B6 first-load budget: the hardware-settings drawer's markup is a fifth of the page and isn't
// needed for the first paint. It is inserted with the drawer's code (and before Mission
// Control, whose Hardware section borrows the drawer's tabs).
import { applyTranslations } from './i18n.js';
import { ZettEventBus } from './event-bus.js';

let pending = null;

export function isDrawerDomReady() {
  return !!document.getElementById('led-drawer');
}

/** Runs fn once the drawer's markup is in the page (now, if it already is). */
export function whenDrawerDom(fn) {
  if (isDrawerDomReady()) fn();
  else ZettEventBus.once('dom:drawer-ready', fn);
}

export function ensureDrawerDom() {
  if (isDrawerDomReady()) return Promise.resolve();
  if (!pending) {
    pending = import('./windows/drawer.html?raw').then(({ default: markup }) => {
      if (!isDrawerDomReady()) {
        const slot = document.getElementById('led-drawer-slot');
        if (slot) slot.insertAdjacentHTML('beforebegin', markup);
        else document.body.insertAdjacentHTML('beforeend', markup);
        slot?.remove();
      }
      applyTranslations();
      ZettEventBus.emit('dom:drawer-ready');
    });
  }
  return pending;
}
