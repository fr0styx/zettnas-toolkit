// The dock's hover previews say their counts and fallbacks in the reader's language.
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api.js', () => {
  const api = { get: vi.fn(async () => ({})), post: vi.fn(async () => ({})), put: vi.fn(async () => ({})), delete: vi.fn(async () => ({})) };
  return { api, default: api, auth: { getToken: () => 'test-token', getUser: () => ({ username: 'admin', role: 'superadmin' }) } };
});

const preview = () => document.getElementById('dock-tooltip-preview-content');

describe('Dock preview words', () => {
  let DockManager;
  let state;
  beforeEach(async () => {
    document.body.innerHTML = '<div id="os-dock-container" class="os-dock-container dock-pos-bottom"><div id="os-dock" class="os-dock active"></div></div>';
    ({ DockManager } = await import('../components/dock.js'));
    ({ state } = await import('../state.js'));
    DockManager.windows = {};
    DockManager.render();
  });
  const home = () => document.querySelector('#os-dock .dock-item[aria-label="Dashboard Home"]');

  it('counts open windows with a plural', () => {
    const el = document.createElement('div'); el.id = 'vm'; el.className = 'os-window'; document.body.append(el);
    DockManager.register('vm', el, 'screen', 'Virtual Machines');
    DockManager.showTooltip(home(), 'home', 'Dashboard Home', '#i-globe', false, false);
    expect(preview().textContent).toContain('1 active window');
    expect(preview().textContent).not.toContain('1 active windows');
  });

  it('names an alert without a title', () => {
    state.latestStats = { events: [{ ts: 4102444800, level: 'warning', message: 'no title here' }] };
    DockManager.showTooltip(home(), 'notif', 'Notification Center', '#i-bell', false, false);
    expect(preview().querySelector('.dock-notif-feed-item-title').textContent).toBe('Alert');
  });

  it('shows the copy preview from the copy toast, and words of its own without one', () => {
    DockManager.showTooltip(home(), 'copy', 'Copy', '#i-copy', false, false);
    expect(preview().textContent).toContain('Copying');
    expect(preview().textContent).toContain('Preparing…');
    document.body.insertAdjacentHTML('beforeend', '<span id="copy-toast-status">Importing</span><span id="copy-toast-pct">40%</span><span id="copy-toast-file">a.jpg</span>');
    DockManager.showTooltip(home(), 'copy', 'Copy', '#i-copy', false, false);
    expect(preview().textContent).toContain('Importing');
    expect(preview().textContent).toContain('a.jpg');
    expect(preview().querySelector('.dkp-bar-fill').style.width).toBe('40%');
  });
});
