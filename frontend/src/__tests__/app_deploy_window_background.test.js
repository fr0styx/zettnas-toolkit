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

    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/resolve')) {
        return { app_id: 'uptime-kuma', default_port: 3001, suggested_port: 3001, conflict_detected: false };
      }
      if (url.includes('/check_port')) {
        return { port: 3001, proto: 'tcp', available: true };
      }
      return {
        apps: [{ id: 'uptime-kuma', name: 'Uptime Kuma', default_port: 3001, category: 'utilities', description: 'Monitor' }],
      };
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
    await deployBtn.onclick();

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

  it('displays port conflict alert banner and auto-suggests free port when pre-deployed container is present', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/resolve')) {
        return {
          app_id: 'uptime-kuma',
          default_port: 3001,
          suggested_port: 3002,
          conflict_detected: true,
          in_use_by: "container 'uptime-kuma'",
          existing_container: { name: 'uptime-kuma', id: '193158e06cff', running: true },
          reason: "Port 3001 is already in use by container 'uptime-kuma'.",
        };
      }
      if (url.includes('/check_port?port=3001')) {
        return { port: 3001, proto: 'tcp', available: false, in_use_by: "container 'uptime-kuma'" };
      }
      if (url.includes('/check_port?port=3002')) {
        return { port: 3002, proto: 'tcp', available: true, in_use_by: null };
      }
      return {
        apps: [{ id: 'uptime-kuma', name: 'Uptime Kuma', default_port: 3001, category: 'utilities', description: 'Monitor' }],
      };
    });

    await openAppDeployModal('uptime-kuma');

    const portInput = document.getElementById('adm-port-input');
    const banner = document.getElementById('adm-conflict-banner');
    const deployBtn = document.getElementById('adm-deploy-confirm-btn');

    // Input automatically remapped to suggested free port 3002
    expect(portInput.value).toBe('3002');
    // Banner alerts user of the port conflict and existing container
    expect(banner.innerHTML).toContain('Port Conflict Detected');
    expect(banner.innerHTML).toContain("container 'uptime-kuma'");
    expect(banner.innerHTML).toContain('3002');

    // If user manually types the occupied port 3001
    portInput.value = '3001';
    portInput.oninput();

    // Wait for debounced port check
    await new Promise((r) => setTimeout(r, 350));

    expect(banner.innerHTML).toContain('Port 3001 is already busy');
    expect(deployBtn.disabled).toBe(true);

    // If user sets back to free port 3002
    portInput.value = '3002';
    portInput.oninput();

    await new Promise((r) => setTimeout(r, 350));

    expect(banner.innerHTML).toContain('Port 3002 is free and ready');
    expect(deployBtn.disabled).toBe(false);
  });

  it('provides confirmation choices when existing container is found and allows custom container name', async () => {
    let deployPayload = null;

    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/resolve')) {
        return {
          app_id: 'uptime-kuma',
          default_port: 3001,
          suggested_port: 3002,
          conflict_detected: true,
          in_use_by: "container 'uptime-kuma'",
          existing_container: { name: 'uptime-kuma', id: 'cid_kuma_1', state: 'running' },
          suggested_container_name: 'uptime-kuma-2',
          reason: "Port 3001 is already in use by container 'uptime-kuma'.",
        };
      }
      if (url.includes('/check_container_name?name=uptime-kuma')) {
        return { name: 'uptime-kuma', exists: true, running: true };
      }
      if (url.includes('/check_container_name?name=uptime-kuma-2')) {
        return { name: 'uptime-kuma-2', exists: false, running: false };
      }
      if (url.includes('/check_container_name?name=my-custom-kuma')) {
        return { name: 'my-custom-kuma', exists: false, running: false };
      }
      if (url.includes('/check_port?port=3001')) {
        return { port: 3001, proto: 'tcp', available: false, in_use_by: "container 'uptime-kuma'" };
      }
      if (url.includes('/check_port?port=3002') || url.includes('/check_port?port=3005')) {
        return { port: 3002, proto: 'tcp', available: true, in_use_by: null };
      }
      return { apps: [] };
    });

    vi.spyOn(api, 'request').mockImplementation(async (url, opts) => {
      if (url.includes('/deploy')) {
        deployPayload = opts.body;
        return {
          ok: true,
          status: 200,
          text: async () => JSON.stringify({ step: 'init', percent: 5, message: 'Starting' }),
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    await openAppDeployModal('uptime-kuma');

    const existingBox = document.getElementById('adm-existing-box');
    const existingBadge = document.getElementById('adm-existing-status-badge');
    const replaceBtn = document.getElementById('adm-choice-replace-btn');
    const newBtn = document.getElementById('adm-choice-new-btn');
    const nameInput = document.getElementById('adm-name-input');
    const portInput = document.getElementById('adm-port-input');
    const deployBtn = document.getElementById('adm-deploy-confirm-btn');

    // Existing container UI box is visible
    expect(existingBox.style.display).toBe('flex');
    expect(existingBadge.textContent).toBe('RUNNING');

    // Defaults to Deploy Alongside: suggested name 'uptime-kuma-2', suggested port 3002
    expect(nameInput.value).toBe('uptime-kuma-2');
    expect(portInput.value).toBe('3002');
    expect(deployBtn.textContent).toContain('Deploy New Instance');

    // User switches to "Stop & Replace Existing"
    replaceBtn.click();
    expect(nameInput.value).toBe('uptime-kuma');
    expect(portInput.value).toBe('3001');
    expect(deployBtn.textContent).toContain('Stop, Replace & Launch');

    // User switches back to "Deploy Alongside (New)"
    newBtn.click();
    expect(nameInput.value).toBe('uptime-kuma-2');
    expect(portInput.value).toBe('3002');
    expect(deployBtn.textContent).toContain('Deploy New Instance');

    // User customizes the container name and port manually
    nameInput.value = 'my-custom-kuma';
    portInput.value = '3005';
    nameInput.oninput();
    portInput.oninput();

    await new Promise((r) => setTimeout(r, 350));

    // Submit deployment
    await deployBtn.onclick();

    // Verify request payload includes customized container_name and replace_existing flag
    expect(deployPayload).toBeTruthy();
    expect(deployPayload.container_name).toBe('my-custom-kuma');
    expect(deployPayload.host_port).toBe(3005);
    expect(deployPayload.replace_existing).toBe(false);
  });
});
