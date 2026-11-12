/** SET-18 (X1, X2): the sidebar as approved, its Advanced group, and the links to its names. */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { installSidebarGroups, setAdvancedGroup } from '../components/management/overview.js';
import { ROUTES, routeFromHash } from '../router.js';
import { canOpen } from '../route-access.js';

const html = readFileSync(resolve(__dirname, '../windows/management-window.html'), 'utf8');
const nav = () => html.slice(html.indexOf('<nav class="mgmt-sidebar-nav"'), html.indexOf('</nav>'));

describe('the sidebar (SET-18)', () => {
  it('has the approved entries in order, Calendar kept, Files and Apps gone', () => {
    const keys = [...nav().matchAll(/class="mgmt-sidebar-text" data-i18n="([a-z_.]+)"/g)].map((m) => m[1]);
    expect(keys).toEqual([
      'mgmt.sidebar_search', 'mgmt.sidebar_overview', 'mgmt.sidebar_activity', 'mgmt.sidebar_calendar',
      'mgmt.sidebar_storage', 'mgmt.sidebar_shared_folders', 'mgmt.sidebar_backup',
      'mgmt.sidebar_people', 'mgmt.sidebar_away', 'mgmt.sidebar_notifications',
      'mgmt.sidebar_kib', 'mgmt.sidebar_appearance', 'mgmt.sidebar_security', 'mgmt.sidebar_general',
      'mgmt.sidebar_network', 'mgmt.sidebar_ups', 'mgmt.sidebar_hardware', 'mgmt.sidebar_vms', 'mgmt.sidebar_connections',
    ]);
    const heads = [...nav().matchAll(/data-i18n="(mgmt\.cat_[a-z_]+)"/g)].map((m) => m[1]);
    expect(heads).toEqual(['mgmt.cat_files_backups', 'mgmt.cat_people_access', 'mgmt.cat_this_nas', 'mgmt.cat_advanced']);
    expect((nav().match(/data-group="advanced"/g) || []).length).toBe(5);
  });

  describe('the Advanced group', () => {
    beforeEach(() => {
      localStorage.clear();
      document.body.innerHTML = `<nav class="mgmt-sidebar-nav"><button id="mgmt-advanced-group" aria-expanded="true"></button>
        <button class="mgmt-sidebar-item" data-group="advanced"></button></nav>`;
    });

    it('starts folded, opens and folds with a click, and this browser remembers it', () => {
      installSidebarGroups();
      const toggle = document.getElementById('mgmt-advanced-group');
      const n = document.querySelector('.mgmt-sidebar-nav');
      expect(toggle.getAttribute('aria-expanded')).toBe('false');
      expect(n.classList.contains('advanced-folded')).toBe(true);
      toggle.click();
      expect(toggle.getAttribute('aria-expanded')).toBe('true');
      expect(localStorage.getItem('kiboto_sidebar_advanced_open')).toBe('1');
      installSidebarGroups(); // a second call binds nothing twice
      toggle.click();
      expect(n.classList.contains('advanced-folded')).toBe(true);
    });

    it('opens as left last time, and does nothing without its markup', () => {
      localStorage.setItem('kiboto_sidebar_advanced_open', '1');
      installSidebarGroups();
      expect(document.getElementById('mgmt-advanced-group').getAttribute('aria-expanded')).toBe('true');
      document.body.innerHTML = '';
      expect(() => setAdvancedGroup(true)).not.toThrow();
      expect(() => installSidebarGroups()).not.toThrow();
    });
  });

  it('links to the new names open their places; the old ones still do', () => {
    const open = vi.fn();
    window.openManagementSection = open;
    for (const [route, target] of [['people', 'mgmt-pane-users'], ['folders', 'mgmt-pane-storage-shares'], ['kib', 'mgmt-sec-ai'],
      ['away', 'mgmt-pane-network-wireguard'], ['notifications', 'mgmt-pane-notifications'], ['security', 'mgmt-pane-security'],
      ['general', 'mgmt-pane-about'], ['connections', 'mgmt-pane-security'], ['calendar', 'mgmt-sec-calendar']]) {
      expect(routeFromHash(`#/${route}`)).toBe(route);
      ROUTES[route]();
      expect(open).toHaveBeenLastCalledWith(target);
    }
    for (const old of ['users', 'shares', 'ai', 'network', 'backup']) expect(routeFromHash(`#/${old}`)).toBe(old);
  });

  it('a family member sees no household set-up entries', () => {
    const family = { scopes: ['storage:read', 'shares:read'] };
    for (const r of ['away', 'notifications', 'security', 'connections', 'people', 'kib']) expect(canOpen(r, family)).toBe(false);
    for (const r of ['appearance', 'general', 'calendar']) expect(canOpen(r, family)).toBe(true);
  });
});

describe('Search settings', () => {
  it('Spotlight registers itself, so the sidebar and the desktop menu can open it without loading it', async () => {
    const { initSpotlight, openSpotlight } = await import('../components/spotlight.js');
    delete window.openSpotlight;
    initSpotlight();
    expect(window.openSpotlight).toBe(openSpotlight);
  });
});
