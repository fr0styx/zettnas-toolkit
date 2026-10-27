/**
 * Advanced (UX-2, B11 UX-23): one switch per person, kept on the server, that hides the places
 * a household rarely needs (virtual machines, network, hardware, power, activity) everywhere:
 * Mission Control, the desktop icons, the dock, the phone launcher and Spotlight.
 * Off for family roles and new accounts; on for accounts that had everything before.
 */
import { ZettEventBus } from './event-bus.js';

export const ADVANCED_SECTIONS = ['mgmt-sec-vms', 'mgmt-sec-network', 'mgmt-sec-hardware', 'mgmt-sec-ups', 'mgmt-sec-activity'];
export const ADVANCED_ROUTES = ['network', 'power', 'vms', 'activity'];
export const ADVANCED_DOCK_APPS = ['vm'];
export const ADVANCED_SPOTLIGHT = ['act-quiet-fans', 'act-perf-fans', 'act-fan-pct', 'act-spindown', 'act-locate-drive', 'act-isolate-container'];
const PREF = 'zettnas_advanced';

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
  if (typeof api?.put !== 'function') return;
  try {
    await api.put('/api/auth/me/preferences', { advanced: _server });
  } catch {
    /* offline: the choice still applies here */
  }
}

export const isAdvancedSection = (s) => ADVANCED_SECTIONS.includes(s);
export const isAdvancedRoute = (r) => ADVANCED_ROUTES.includes(r);

/** Hides or shows the advanced places that are already on screen, and tells the rest. */
export function applyAdvancedEverywhere(on = advancedOn(), root = document) {
  root.querySelectorAll('[data-advanced-section]').forEach((el) => {
    if (isAdvancedSection(el.dataset.advancedSection)) el.style.display = on ? '' : 'none';
  });
  root.querySelectorAll('[data-phone-open]').forEach((el) => {
    if (isAdvancedRoute(el.dataset.phoneOpen)) el.hidden = !on;
  });
  ZettEventBus.emit('advanced:changed', { on });
}
