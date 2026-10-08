import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fetchAndRenderSystemAbout } from '../components/management.js';
import { api } from '../api.js';

describe('System About & Software Updates Frontend Component', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="mgmt-pane-about">
        <span id="about-version-badge">v1.0.0 • Loading</span>
        <span id="about-chassis-model">-</span>
        <span id="about-host-platform">-</span>
        <span id="about-runtime-env">-</span>
        <span id="about-system-uptime">-</span>

        <span id="update-status-icon">🔄</span>
        <div id="update-status-title">Checking for updates...</div>
        <div id="update-status-desc">Connecting...</div>
        <span id="update-last-checked">Never</span>

        <div id="update-details-box" style="display: none;">
          <h4 id="update-release-title">Release</h4>
          <a id="update-release-link" href="#">View on GitHub</a>
          <pre id="update-release-notes"></pre>
        </div>

        <button id="btn-check-updates">
          <span id="btn-check-updates-icon">🔄</span>
          <span id="btn-check-updates-text">Check for Updates</span>
        </button>
      </div>
    `;
    vi.restoreAllMocks();
  });

  it('renders system telemetry and up-to-date status cleanly', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/system/about') {
        return {
          name: 'ZettNAS Workbench',
          version: '1.5.0',
          tag: 'v1.5.0',
          release_channel: 'Stable',
          chassis_model: 'Zettlab D8 (8-Bay)',
          hostname: 'ZettTower',
          platform: 'Linux 6.12.13-Unraid',
          containerized: true,
          python_version: '3.12.15',
          uptime_secs: 90060, // 1d 1h 1m
        };
      }
      if (url.startsWith('/api/system/updates')) {
        return {
          current_version: '1.5.0',
          latest_version: '1.5.0',
          latest_tag: 'v1.5.0',
          update_available: false,
          checked_at: 1775685600,
        };
      }
      return null;
    });

    await fetchAndRenderSystemAbout();

    expect(document.getElementById('about-version-badge').textContent).toBe('v1.5.0 • Stable');
    expect(document.getElementById('about-chassis-model').textContent).toBe('Zettlab D8 (8-Bay)');
    expect(document.getElementById('about-host-platform').textContent).toBe('ZettTower (Linux 6.12.13-Unraid)');
    expect(document.getElementById('about-runtime-env').textContent).toBe('Docker Container (Python 3.12.15)');
    expect(document.getElementById('about-system-uptime').textContent).toBe('1d 1h 1m');

    expect(document.getElementById('update-status-icon').textContent).toBe('✅');
    expect(document.getElementById('update-status-title').textContent).toBe('ZettNAS Workbench is up to date');
    expect(document.getElementById('update-details-box').style.display).toBe('none');
    expect(document.getElementById('btn-check-updates-text').textContent).toBe('Check for Updates');
  });

  it('renders update available state with release notes and link', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/system/about') {
        return {
          name: 'ZettNAS Workbench',
          version: '1.5.0',
          tag: 'v1.5.0',
          release_channel: 'Stable',
          chassis_model: 'Zettlab D4 (4-Bay)',
          uptime_secs: 3660,
        };
      }
      if (url.startsWith('/api/system/updates')) {
        return {
          current_version: '1.5.0',
          latest_version: '1.6.0',
          latest_tag: 'v1.6.0',
          update_available: true,
          release_name: 'ZettNAS v1.6.0 Enterprise Speed',
          release_url: 'https://github.com/fr0styx/zettnas-toolkit/releases/tag/v1.6.0',
          release_notes: '## Improvements\n- High-velocity NVMe telemetry',
          checked_at: 1775685600,
        };
      }
      return null;
    });

    await fetchAndRenderSystemAbout(true);

    expect(document.getElementById('update-status-icon').textContent).toBe('🚀');
    expect(document.getElementById('update-status-title').textContent).toContain('Update Available: v1.6.0');
    expect(document.getElementById('update-details-box').style.display).toBe('block');
    expect(document.getElementById('update-release-title').textContent).toBe('ZettNAS v1.6.0 Enterprise Speed');
    expect(document.getElementById('update-release-link').href).toBe('https://github.com/fr0styx/zettnas-toolkit/releases/tag/v1.6.0');
    expect(document.getElementById('update-release-notes').textContent).toContain('High-velocity NVMe telemetry');
  });

  it('handles network failure gracefully', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('Network disconnected'));

    await fetchAndRenderSystemAbout();

    expect(document.getElementById('update-status-icon').textContent).toBe('⚠️');
    expect(document.getElementById('update-status-title').textContent).toBe('Unable to check for updates');
    expect(document.getElementById('update-status-desc').textContent).toBe('Network disconnected');
    expect(document.getElementById('btn-check-updates-text').textContent).toBe('Check for Updates');
  });
});
