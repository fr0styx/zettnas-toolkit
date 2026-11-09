// The dock's Home button hides and brings back open windows only; closed ones stay closed.
import { describe, expect, it, vi } from 'vitest';

vi.mock('../api.js', () => {
  const api = { get: vi.fn(async () => ({})), post: vi.fn(async () => ({})), put: vi.fn(async () => ({})), delete: vi.fn(async () => ({})) };
  return { api, default: api, auth: { getToken: () => 'test-token', getUser: () => ({ username: 'admin', role: 'superadmin' }) } };
});

const mk = (id) => {
  const el = document.createElement('div');
  el.id = id;
  el.className = 'os-window';
  document.body.appendChild(el);
  return el;
};

describe('Dock Home button', () => {
  it('leaves closed windows closed', async () => {
    document.body.innerHTML = '<div id="os-dock-container" class="os-dock-container dock-pos-bottom"><div id="os-dock" class="os-dock active"></div></div>';
    const { DockManager } = await import('../components/dock.js');
    DockManager.windows = {};
    DockManager.register('stack-inspector', mk('stack-inspector'), '#i-grid', 'Stack Inspector', true);
    DockManager.register('container-inspector', mk('container-inspector'), '#i-chip', 'Container details', true);
    DockManager.register('vm', mk('vm'), 'screen', 'Virtual Machines');
    const home = () => document.querySelector('#os-dock .dock-item[aria-label="Dashboard Home"]').click();

    home(); // hides the open window
    expect(DockManager.windows.vm.minimized).toBe(true);
    home(); // brings it back, and nothing else
    expect(DockManager.windows.vm.minimized).toBe(false);
    expect(DockManager.windows['stack-inspector'].closed).toBe(true);
    expect(DockManager.windows['container-inspector'].closed).toBe(true);
    expect(document.getElementById('stack-inspector').style.display).toBe('none');
  });

  it('counts a closed Stack Inspector as closed', async () => {
    document.body.innerHTML = '<div id="os-dock-container" class="os-dock-container dock-pos-bottom"><div id="os-dock" class="os-dock active"></div></div>';
    const { DockManager } = await import('../components/dock.js');
    const { closeStackModal } = await import('../components/stack-modal.js');
    DockManager.windows = {};
    const overlay = mk('stack-inspector-overlay');
    DockManager.register('stack-inspector', overlay, '#i-grid', 'Stack Inspector');
    expect(DockManager.windows['stack-inspector'].closed).toBe(false);
    closeStackModal();
    expect(DockManager.windows['stack-inspector'].closed).toBe(true);
    document.querySelector('#os-dock .dock-item[aria-label="Dashboard Home"]').click();
    expect(DockManager.windows['stack-inspector'].minimized).toBe(true);
    expect(overlay.style.display).toBe('none');
  });

  it('the desktop preview under Home leaves closed windows closed too', async () => {
    document.body.innerHTML = '<div id="os-dock-container" class="os-dock-container dock-pos-bottom"><div id="os-dock" class="os-dock active"></div></div>';
    const { DockManager } = await import('../components/dock.js');
    DockManager.windows = {};
    DockManager.register('stack-inspector', mk('stack-inspector'), '#i-grid', 'Stack Inspector', true);
    DockManager.register('vm', mk('vm'), 'screen', 'Virtual Machines');
    DockManager.minimize('vm');
    const home = document.querySelector('#os-dock .dock-item[aria-label="Dashboard Home"]');
    DockManager.showTooltip(home, 'home', 'Dashboard Home', '#i-globe', false, false);
    const card = document.querySelector('.dock-preview-desktop-home');
    expect(card).not.toBeNull();
    card.click(); // nothing showing: brings back the minimized window only
    expect(DockManager.windows.vm.minimized).toBe(false);
    expect(DockManager.windows['stack-inspector'].closed).toBe(true);
    expect(document.getElementById('stack-inspector').style.display).toBe('none');
  });

  it('closes a Stack Inspector the dock never saw', async () => {
    const { DockManager } = await import('../components/dock.js');
    const { closeStackModal } = await import('../components/stack-modal.js');
    DockManager.windows = {};
    expect(() => closeStackModal()).not.toThrow();
    expect(DockManager.windows['stack-inspector']).toBeUndefined();
  });
});
