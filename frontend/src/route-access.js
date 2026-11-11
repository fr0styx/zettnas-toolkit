// Which places an account can use (NUX-5): one map from a place to the rights that open it, so
// kids, guests and family accounts aren't shown places that only answer "no permission".
import { ZettEventBus } from './event-bus.js';
import { onManagementDom } from './management-dom.js';
import { NO_ACCESS, leavePage, mark, tidyHeadings } from './hide-marks.js';

// place -> any of these scopes opens it; a place not listed is open to everyone
let _user = null;

export const ROUTE_SCOPES = {
  apps: ['containers:read', 'containers:manage'],
  'apps/catalog': ['containers:manage'],
  storage: ['storage:read'],
  drives: ['storage:read', 'hardware:read'],
  shares: ['shares:manage', 'storage:admin'],
  backup: ['backup:read', 'backup:manage'],
  users: ['users:read'],
  network: ['system:config'],
  power: ['hardware:read', 'system:power'],
  ai: ['system:config'],
  vms: ['vms:manage', 'vms:read'],
  activity: ['logs:read'],
  hardware: ['hardware:read'],
};

/** The server's rule (backend/auth.py has_scope): "*", "*:read" for reads, "area:*", exact. */
export function hasScope(scopes, need) {
  const list = scopes || [];
  if (list.includes('*') || list.includes(need)) return true;
  const [area, verb] = need.split(':');
  if (list.includes(`${area}:*`)) return true;
  return (verb === 'read' || verb === 'view') && list.includes('*:read');
}

// Spotlight commands -> any of these scopes runs them (NUX-5); others are open to everyone
export const SPOTLIGHT_SCOPES = {
  'app-smart': ['storage:read', 'hardware:read'],
  'app-catalog': ['containers:manage'],
  'act-quiet-fans': ['hardware:fans'],
  'act-perf-fans': ['hardware:fans'],
  'act-fan-pct': ['hardware:fans'],
  'act-spindown': ['storage:admin'],
  'act-snap-pool': ['storage:admin'],
  'act-locate-drive': ['storage:admin'],
  'act-trash-empty': ['shares:manage', 'storage:admin'],
  'dyn-trash-empty': ['shares:manage', 'storage:admin'],
  'act-isolate-container': ['containers:manage'],
};

/** Whether this account may run a Spotlight command; true while the account isn't known. */
export function canRun(id, user) {
  const need = SPOTLIGHT_SCOPES[id];
  return !need || !user || need.some((s) => hasScope(user.scopes, s));
}

export function currentUser() {
  return _user;
}

export function canOpen(route, user) {
  const need = ROUTE_SCOPES[route];
  if (!need) return true;
  if (!user) return true; // not known yet: shown until the account is
  return need.some((s) => hasScope(user.scopes, s));
}

/** Hides launcher tiles, tabs, Mission Control's sidebar entries and anything else marked
 *  with a place (data-route) this account can't use. */
export function hideUnusable(root, user) {
  if (!root) return;
  // the Overview's cards too: they carried no place, so a family member saw cards that lead to
  // pages the sidebar hides from them (SET-12)
  for (const el of root.querySelectorAll('[data-phone-open], [data-phone-tab], [data-route], .mgmt-app-card[data-mgmt-target]')) {
    const route = routeOf(el);
    if (route) mark(el, NO_ACCESS, !canOpen(route, user)); // one reason among others: see hide-marks.js
  }
  tidyHeadings(root);
}

// the Overview's cards by the place they open
export const CARD_ROUTES = {
  'mgmt-sec-storage': 'storage',
  'mgmt-sec-docker': 'apps',
  'mgmt-sec-ai': 'ai',
  'mgmt-sec-vms': 'vms',
  'mgmt-sec-network': 'network',
  'mgmt-sec-ups': 'power',
  'mgmt-sec-hardware': 'hardware',
  'mgmt-sec-activity': 'activity',
};

/** The place an element opens, or ''. */
export function routeOf(el) {
  return el.getAttribute('data-phone-open') || el.getAttribute('data-phone-tab') || el.getAttribute('data-route') || CARD_ROUTES[el.getAttribute('data-mgmt-target')] || '';
}

ZettEventBus.on?.('session:user', (user) => {
  _user = user;
  hideUnusable(document, user);
  leavePage(NO_ACCESS); // the page that was open may be one this account cannot use
});
onManagementDom(() => hideUnusable(document, _user)); // Mission Control arrives later
