/** SET-20: "Search settings" finds the Settings pages by name and by everyday words. */
import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest';
import { setLanguage } from '../i18n.js';
import { ZettEventBus } from '../event-bus.js';
import { initSpotlight, openSpotlight, closeSpotlight, filterSpotlightResults, loadSpotlightPages, relabelSpotlight } from '../components/spotlight.js';
import { PAGES, TABS, TASKS, pageItems, tabItems, taskItems, words } from '../components/spotlight-pages.js';

const titles = () => [...document.querySelectorAll('#spotlight-results .spotlight-result-item')].map((e) => e.textContent);

// household words and the page each should find
const ASKED = [
  ['tailscale', 'Away from home'],
  ['password', 'Security'],
  ['wallpaper', 'Appearance'],
  ['battery', 'Power'],
  ['kids', 'People'],
  ['restore', 'Backup'],
  ['fans', 'Hardware'],
  ['update', 'General'],
  ['samba', 'Shared folders'],
  ['what happened', 'Activity'],
  ['sign out', 'My account'],
  ['time zone', 'Time, Language & Region'],
  ['fan curve', 'Fans'],
  ['dropbox', 'Remote & Cloud Storage'],
  ['dark mode', 'Switch between dark and light'],
  ['fan noise', 'Make the fans quieter'],
  ['add a person', 'Add a person'],
  ['deleted', 'Get a file back'],
];

describe('Spotlight finds Settings pages (SET-20)', () => {
  beforeAll(async () => {
    document.body.innerHTML = '';
    initSpotlight();
    await loadSpotlightPages();
  });
  afterAll(() => closeSpotlight());

  it.each(ASKED)('"%s" finds %s', (word, page) => {
    openSpotlight();
    filterSpotlightResults(word);
    expect(titles().some((x) => x.includes(page))).toBe(true);
  });

  it('every page has a route and words, and opens its route', () => {
    for (const [route] of PAGES) expect(pageItems().find((i) => i.id === `page-${route}`).keywords.length).toBeGreaterThan(2);
    window.openManagementSection = vi.fn();
    pageItems().find((i) => i.route === 'away').run();
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-pane-network-wireguard');
    delete window.openManagementSection;
    expect(words(' A, b ,, ')).toEqual(['a', 'b']);
    expect(words(undefined)).toEqual([]);
    expect(tabItems()).toHaveLength(TABS.length);
    window.openManagementSection = vi.fn();
    tabItems().find((i) => i.id === 'tab-mgmt-pane-events').run();
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-pane-events');
    delete window.openManagementSection;
    expect(() => tabItems()[0].run()).not.toThrow();
    expect(taskItems()).toHaveLength(TASKS.length);
    const fans = taskItems().find((i) => i.id === 'task-fans');
    expect(fans.subtitle).toBe('Hardware · Settings');
    window.openManagementSection = vi.fn();
    fans.run();
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-pane-hardware-fans');
    taskItems().find((i) => i.id === 'task-share').run();
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-pane-storage-shares');
    delete window.openManagementSection;
  });

  it('hides a page this account cannot open', () => {
    ZettEventBus.emit('session:user', { username: 'kid', scopes: ['shares:read'] });
    openSpotlight();
    filterSpotlightResults('tailscale');
    expect(titles().some((x) => x.includes('Away from home'))).toBe(false);
    ZettEventBus.emit('session:user', null);
  });

  it('finds German words, and English ones still, after a change of language', async () => {
    await setLanguage('de');
    relabelSpotlight();
    openSpotlight();
    filterSpotlightResults('passwort ändern');
    expect(titles().some((x) => x.includes('Mein Passwort ändern'))).toBe(true);
    filterSpotlightResults('lüfter');
    expect(titles().some((x) => x.includes('Hardware'))).toBe(true);
    filterSpotlightResults('battery');
    expect(titles().some((x) => x.includes('Strom') || x.includes('Power') || x.includes('USV'))).toBe(true);
    await setLanguage('en');
    relabelSpotlight();
  });
});
