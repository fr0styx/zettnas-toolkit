import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { openAppDeployModal } from '../components/management.js';
import { DockManager, bringToFront } from '../components/dock.js';
import { api } from '../api.js';

describe('App Catalog Deployment Window - Background & Minimize Suite', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="desktop">
        <div id="management-modal-overlay" class="open" style="display:flex; z-index:1000;">
          <div id="management-window" class="smart-modal-window active-window" style="z-index:1000;">
            <div id="mgmt-content"></div>
          </div>
        </div>
      </div>
      <div id="os-dock-container">
        <div id="os-dock"></div>
      </div>
    `;

    vi.spyOn(api, 'get').mockResolvedValue({
      apps: [{ id: 'uptime-kuma', name: 'Uptime Kuma', default_port: 3001, category: 'utilities', description: 'Monitor' }],
    });
    vi.spyOn(api, 'request').mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ default_port: 3001, compose_yaml: 'version: "3.8"' }),
    });
  });

  afterEach(() => {
    const modal = document.getElementById('app-deploy-modal-overlay');
    if (modal && modal._close) modal._close();
    vi.restoreAllMocks();
  });

  it('opens deploy modal as an active desktop window with minimize and close controls registered in DockManager', async () => {
    await openAppDeployModal('uptime-kuma');

    const overlay = document.getElementById('app-deploy-modal-overlay');
    const win = document.getElementById('app-deploy-modal-window');
    const minBtn = document.getElementById('adm-min-btn');
    const closeBtn = document.getElementById('adm-close-btn');

    expect(overlay).toBeTruthy();
    expect(win).toBeTruthy();
    expect(minBtn).toBeTruthy();
    expect(closeBtn).toBeTruthy();

    expect(overlay.classList.contains('open')).toBe(true);
    expect(overlay.classList.contains('window-minimized')).toBe(false);

    // DockManager has registered app-deploy
    expect(DockManager.windows['app-deploy']).toBeTruthy();
    expect(DockManager.windows['app-deploy'].minimized).toBe(false);
  });

  it('minimizes to dock when minimize button is clicked and restores when dock item is clicked', async () => {
    await openAppDeployModal('uptime-kuma');

    const overlay = document.getElementById('app-deploy-modal-overlay');
    const minBtn = document.getElementById('adm-min-btn');

    // Click minimize button
    minBtn.click();

    expect(overlay.classList.contains('window-minimized')).toBe(true);
    expect(overlay.style.display).toBe('none');
    expect(DockManager.windows['app-deploy'].minimized).toBe(true);

    // Restore from dock
    DockManager.restore('app-deploy');

    expect(overlay.classList.contains('window-minimized')).toBe(false);
    expect(overlay.classList.contains('open')).toBe(true);
    expect(overlay.style.display).toBe('flex');
    expect(DockManager.windows['app-deploy'].minimized).toBe(false);
  });

  it('allows operating the OS in the background while deployment is actively streaming', async () => {
    const mockNdjson = [
      JSON.stringify({ step: 'init', percent: 10, message: 'Pulling layers' }),
      JSON.stringify({ step: 'pull', percent: 69, message: 'Extracting image' }),
      JSON.stringify({ step: 'success', percent: 100, message: 'Container started', port: 3001, done: true }),
    ].join('\n');

    vi.spyOn(api, 'request').mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => mockNdjson,
    });

    await openAppDeployModal('uptime-kuma');

    const overlay = document.getElementById('app-deploy-modal-overlay');
    const win = document.getElementById('app-deploy-modal-window');
    const deployBtn = document.getElementById('adm-deploy-confirm-btn');
    const closeBtn = document.getElementById('adm-close-btn');
    const mgmtWin = document.getElementById('management-window');

    // Trigger deployment
    deployBtn.onclick();

    // While deploying, close button is NOT disabled
    expect(closeBtn.disabled).toBe(false);
    expect(closeBtn.style.pointerEvents).toBe('auto');

    // User clicks Mission Control window to bring it to front and put deploy window in background
    bringToFront(mgmtWin);
    expect(parseInt(mgmtWin.style.zIndex, 10)).toBeGreaterThan(parseInt(win.style.zIndex, 10));

    // User can minimize deploy window to dock during deployment
    const minBtn = document.getElementById('adm-min-btn');
    minBtn.click();

    expect(overlay.classList.contains('window-minimized')).toBe(true);
    expect(DockManager.windows['app-deploy'].minimized).toBe(true);

    // If user clicks close button while deploying, it minimizes rather than killing the process
    DockManager.restore('app-deploy');
    closeBtn.click();

    expect(overlay.classList.contains('window-minimized')).toBe(true);
    expect(DockManager.windows['app-deploy'].minimized).toBe(true);
  });
});
