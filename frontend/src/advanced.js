/**
 * Advanced (UX-2, B11 UX-23): one switch per person, kept on the server, that hides the places
 * a household rarely needs (virtual machines, network, hardware, power, activity) everywhere:
 * Mission Control, the desktop icons, the dock, the phone launcher and Spotlight.
 * Off for family roles and new accounts; on for accounts that had everything before.
 */
import { ZettEventBus } from './event-bus.js';
import { ADVANCED_OFF, mark } from './hide-marks.js';

export const ADVANCED_SECTIONS = ['mgmt-sec-vms', 'mgmt-sec-network', 'mgmt-sec-hardware', 'mgmt-sec-ups', 'mgmt-sec-activity'];
export const ADVANCED_ROUTES = ['network', 'power', 'vms', 'activity', 'hardware'];
export const ADVANCED_DOCK_APPS = ['vm'];
export const ADVANCED_SPOTLIGHT = ['act-quiet-fans', 'act-perf-fans', 'act-fan-pct', 'act-spindown', 'act-locate-drive', 'act-isolate-container'];
const PREF = 'kiboto_advanced';

let _server = null; // the person's setting from /api/auth/me, once known

export function advancedOn() {
  if (typeof _server === 'boolean') return _server;
  try {
    return localStorage.getItem(PREF) !== '0'; // before sign-in: what this browser last showed
  } catch {
    return true;
  }
}

function remember(on) {
  try {
    localStorage.setItem(PREF, on ? '1' : '0');
  } catch {
    /* private window */
  }
}

/** The signed-in person's setting arrived (users.js). */
export function setServerAdvanced(value) {
  if (typeof value !== 'boolean') return;
  _server = value;
  remember(value);
  applyAdvancedEverywhere(value);
}

/** The person flipped the switch: shown at once, saved to their account. */
export async function saveAdvanced(on, api) {
  _server = Boolean(on);
  remember(_server);
  applyAdvancedEverywhere(_server);
  if (typeof api?.put !== 'function') return true;
  try {
    await api.put('/api/auth/me/preferences', { advanced: _server });
    return true;
  } catch {
    return false; // the choice applies here; the caller says that it was not saved
  }
}

// A UPS is found or the power is out: Power then shows with Advanced off, because that is when a
// household needs it (SET-15, Power decision 2)
let _powerMatters = false;

/** The top bar reports whether power matters here; Power's places follow at once. */
export function setPowerMatters(value) {
  const next = Boolean(value);
  if (next === _powerMatters) return;
  _powerMatters = next;
  applyAdvancedEverywhere();
}

export const isAdvancedSection = (s) => ADVANCED_SECTIONS.includes(s) && !(_powerMatters && s === 'mgmt-sec-ups');
export const isAdvancedRoute = (r) => ADVANCED_ROUTES.includes(r) && !(_powerMatters && r === 'power');

/** Hides or shows the advanced places that are already on screen, and tells the rest. */
export function applyAdvancedEverywhere(on = advancedOn(), root = document) {
  // an advanced place that is shown for now (Power while it matters) loses its mark too
  root.querySelectorAll('[data-advanced-section]').forEach((el) => {
    const s = el.dataset.advancedSection;
    if (ADVANCED_SECTIONS.includes(s)) mark(el, ADVANCED_OFF, !on && isAdvancedSection(s));
  });
  root.querySelectorAll('[data-phone-open]').forEach((el) => {
    const r = el.dataset.phoneOpen;
    if (ADVANCED_ROUTES.includes(r)) mark(el, ADVANCED_OFF, !on && isAdvancedRoute(r)); // never over the person's rights
  });
  ZettEventBus.emit('advanced:changed', { on });
}
