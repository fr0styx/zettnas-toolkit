// Which places an account can use (NUX-5): one map from a place to the rights that open it, so
// kids, guests and family accounts aren't shown places that only answer "no permission".
import { ZettEventBus } from './event-bus.js';
import { onManagementDom } from './management-dom.js';

// place -> any of these scopes opens it; a place not listed is open to everyone
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
  for (const el of root.querySelectorAll('[data-phone-open], [data-phone-tab], [data-route]')) {
    const route = el.getAttribute('data-phone-open') || el.getAttribute('data-phone-tab') || el.getAttribute('data-route');
    if (!canOpen(route, user)) {
      if (!el.hidden) {
        el.hidden = true;
        el.setAttribute('data-no-access', ''); // remembered: only what this hid comes back
      }
    } else if (el.hasAttribute('data-no-access')) {
      el.hidden = false;
      el.removeAttribute('data-no-access');
    }
  }
}

let _user = null;
ZettEventBus.on?.('session:user', (user) => {
  _user = user;
  hideUnusable(document, user);
});
onManagementDom(() => hideUnusable(document, _user)); // Mission Control arrives later
