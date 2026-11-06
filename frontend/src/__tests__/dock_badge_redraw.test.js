// The dock redraws when a window opens or closes; the bell's unread count stays on through it.
import { describe, expect, it, vi } from 'vitest';

vi.mock('../api.js', () => {
  const api = { get: vi.fn(async () => ({})), post: vi.fn(async () => ({})), put: vi.fn(async () => ({})), delete: vi.fn(async () => ({})) };
  return { api, default: api, auth: { getToken: () => 'test-token', getUser: () => ({ username: 'admin', role: 'superadmin' }) } };
});

describe('Dock notification badge', () => {
  it('keeps the unread count when the dock redraws', async () => {
    document.body.innerHTML = '<div id="os-dock-container" class="os-dock-container dock-pos-bottom"><div id="os-dock" class="os-dock active"></div></div>';
    const { state } = await import('../state.js');
    const { DockManager } = await import('../components/dock.js');
    state.latestStats = {
      events: [
        { ts: 4102444800, title: 'Disk sdb hot', level: 'warning', message: '52 C' },
        { ts: 4102444900, title: 'Pool degraded', level: 'error', message: 'sdc missing' },
      ],
    };
    DockManager.render();
    const first = document.getElementById('dock-notif-badge');
    expect(first.textContent).toBe('2');
    expect(first.style.display).toBe('block');

    const win = document.createElement('div');
    win.id = 'file-manager-window';
    win.className = 'os-window';
    document.body.appendChild(win);
    DockManager.register('file-manager-window', win, 'folder', 'File Explorer');
    DockManager.render();
    const after = document.getElementById('dock-notif-badge');
    expect(after).not.toBe(first);
    expect(after.textContent).toBe('2');
    expect(after.style.display).toBe('block');
    expect(after.closest('.dock-notif-btn').getAttribute('aria-label')).toContain('2');
  });
});
