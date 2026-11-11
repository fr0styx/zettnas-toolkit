/**
 * Deep links (UX-4): #/apps, #/apps/catalog, #/files, #/storage, #/shares, #/backup, #/users,
 * #/network, #/power, #/ai, #/vms, #/settings open the one place that does that job.
 */
import { ZettEventBus } from './event-bus.js';

export const ROUTES = {
  apps: () => window.openContainersManager?.(),
  'apps/catalog': () => window.openContainersManager?.({ view: 'catalog' }),
  files: () => window.openFileManager?.(),
  storage: () => window.openManagementSection?.('mgmt-sec-storage'),
  drives: () => ZettEventBus.emit('modal:smart:open', null),
  shares: () => window.openManagementSection?.('mgmt-pane-storage-shares'),
  backup: () => window.openManagementSection?.('mgmt-pane-backups'),
  users: () => window.openManagementSection?.('mgmt-pane-users'),
  network: () => window.openManagementSection?.('mgmt-sec-network'),
  power: () => window.openManagementSection?.('mgmt-sec-ups'),
  ai: () => window.openManagementSection?.('mgmt-sec-ai'),
  vms: () => window.openManagementSection?.('mgmt-sec-vms'),
  settings: () => window.openManagementSection?.('mgmt-sec-system-group'),
  time: () => import('./components/widgets.js').then((m) => m.openTimezoneModal()),
  alerts: () => window.openManagementSection?.('mgmt-pane-notifications'),
  // "activity" is the page of that name in the sidebar; the Event Log has its own word. A link
  // called activity opened the Event Log, and Hardware, Appearance and Overview had no link (SET-12)
  activity: () => section('mgmt-sec-activity'),
  events: () => section('mgmt-pane-events'),
  hardware: () => section('mgmt-sec-hardware'),
  appearance: () => section('mgmt-sec-wallpaper'),
  overview: () => section('management-hub-view'),
};

/** Opens a section of the Settings window by its id. */
function section(id) {
  return /** @type {any} */ (window).openManagementSection?.(id);
}

export function routeFromHash(hash) {
  const m = /^#\/([a-z]+(?:\/[a-z]+)?)\/?$/.exec(hash || '');
  return m && ROUTES[m[1]] ? m[1] : null;
}

export function openRoute(hash) {
  const route = routeFromHash(hash);
  if (!route) return false;
  try {
    ROUTES[route]();
  } catch (e) {
    console.warn('[Kiboto] could not open', route, e);
    return false;
  }
  return true;
}

export function initRouter() {
  window.addEventListener('hashchange', () => openRoute(window.location.hash));
  // after sign-in the windows exist; open the linked place once
  setTimeout(() => openRoute(window.location.hash), 1200);
}
