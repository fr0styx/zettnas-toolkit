import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fetchAndRenderSystemAbout, setUpdateChannel, applySystemUpdate } from '../components/management.js';
import { api } from '../api.js';

describe('System About & Software Updates Frontend Component', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="mgmt-pane-about">
        <span id="about-version-badge">v1.0.0 • Loading</span>
        <span id="about-chassis-model">-</span>
        <span id="about-host-platform">-</span>
        <span id="about-runtime-env">-</span>
        <span id="about-system-uptime">-</span>

        <button id="btn-channel-stable" class="active">Stable</button>
        <button id="btn-channel-edge">Edge</button>

        <span id="update-status-icon">🔄</span>
        <div id="update-status-title">Checking for updates...</div>
        <div id="update-status-desc">Connecting...</div>
        <span id="update-last-checked">Never</span>

        <div id="update-details-box" style="display: none;">
          <h4 id="update-release-title">Release</h4>
          <a id="update-release-link" href="#">View on GitHub</a>
          <pre id="update-release-notes"></pre>
          <button id="btn-apply-system-update" style="display: none;">
            <span id="btn-apply-update-text">Install Update Now</span>
          </button>
          <div id="update-progress-overlay" style="display: none;">
            <div id="update-progress-title">Progress</div>
            <div id="update-progress-desc">Details</div>
          </div>
        </div>

        <button id="btn-check-updates">
          <span id="btn-check-updates-icon">🔄</span>
          <span id="btn-check-updates-text">Check for Updates</span>
        </button>
      </div>
    `;
    vi.restoreAllMocks();
  });

  it('renders system telemetry and up-to-date status cleanly on stable channel', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/system/about') {
        return {
          name: 'ZettNAS Workbench',
          version: '1.8.0',
          tag: 'v1.8.0',
          commit: '5c0639d',
          release_channel: 'Stable',
          chassis_model: 'Zettlab D8 Ultra (8-Bay)',
          hostname: 'ZettTower',
          platform: 'Linux 6.12.13-Unraid',
          containerized: true,
          python_version: '3.12.15',
          uptime_secs: 90060, // 1d 1h 1m
        };
      }
      if (url.startsWith('/api/system/updates')) {
        return {
          channel: 'stable',
          current_version: '1.8.0',
          latest_version: '1.8.0',
          latest_tag: 'v1.8.0',
          update_available: false,
          checked_at: 1775685600,
        };
      }
      return null;
    });

    await fetchAndRenderSystemAbout();

    expect(document.getElementById('about-version-badge').textContent).toBe('v1.8.0 (5c0639d) • Stable');
    expect(document.getElementById('about-chassis-model').textContent).toBe('Zettlab D8 Ultra (8-Bay)');
    expect(document.getElementById('about-host-platform').textContent).toBe('ZettTower (Linux 6.12.13-Unraid)');
    expect(document.getElementById('about-runtime-env').textContent).toBe('Docker Container (Python 3.12.15)');
    expect(document.getElementById('about-system-uptime').textContent).toBe('1d 1h 1m');

    expect(document.getElementById('update-status-icon').textContent).toBe('✅');
    expect(document.getElementById('update-status-title').textContent).toBe('ZettNAS Workbench is up to date');
    expect(document.getElementById('update-details-box').style.display).toBe('none');
    expect(document.getElementById('btn-check-updates-text').textContent).toBe('Check for Updates');
  });

  it('renders update available state with release notes and apply button on stable channel', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/system/about') {
        return {
          name: 'ZettNAS Workbench',
          version: '1.7.0',
          tag: 'v1.7.0',
          release_channel: 'Stable',
          chassis_model: 'Zettlab D4 (4-Bay)',
          uptime_secs: 3660,
        };
      }
      if (url.startsWith('/api/system/updates')) {
        return {
          channel: 'stable',
          current_version: '1.7.0',
          latest_version: '1.8.0',
          latest_tag: 'v1.8.0',
          update_available: true,
          release_name: 'ZettNAS v1.8.0 7-Pillar Architecture',
          release_url: 'https://github.com/fr0styx/zettnas-toolkit/releases/tag/v1.8.0',
          release_notes: '## Improvements\n- 7-Pillar Mission Control\n- Containers Dedicated Window',
          checked_at: 1775685600,
        };
      }
      return null;
    });

    await fetchAndRenderSystemAbout(true);

    expect(document.getElementById('update-status-icon').textContent).toBe('🚀');
    expect(document.getElementById('update-status-title').textContent).toContain('Update Available: v1.8.0');
    expect(document.getElementById('update-details-box').style.display).toBe('block');
    expect(document.getElementById('update-release-title').textContent).toBe('ZettNAS v1.8.0 7-Pillar Architecture');
    expect(document.getElementById('update-release-link').href).toBe('https://github.com/fr0styx/zettnas-toolkit/releases/tag/v1.8.0');
    expect(document.getElementById('update-release-notes').textContent).toContain('7-Pillar Mission Control');
    expect(document.getElementById('btn-apply-system-update').style.display).toBe('flex');
    expect(document.getElementById('btn-apply-update-text').textContent).toContain('Install Release v1.8.0');
  });

  it('allows opting in to Edge channel to download latest commit features', async () => {
    const apiGetSpy = vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/system/about') {
        return {
          name: 'ZettNAS Workbench',
          version: '1.8.0',
          tag: 'v1.8.0',
          commit: 'ed8b87e',
          release_channel: 'Stable',
        };
      }
      if (url.includes('channel=edge')) {
        return {
          channel: 'edge',
          current_version: '1.8.0',
          current_commit: 'ed8b87e',
          latest_version: '5c0639d',
          latest_tag: 'main@5c0639d',
          update_available: true,
          release_name: 'main @ 5c0639d: fix(ci): restore ruff target-version',
          release_url: 'https://github.com/fr0styx/zettnas-toolkit/commit/5c0639d',
          release_notes: 'Author: fr0styx\nCommit: 5c0639d\nMessage: fix(ci): restore ruff target-version',
          checked_at: 1775685600,
        };
      }
      return null;
    });

    await setUpdateChannel('edge');

    expect(localStorage.getItem('zettnas_update_channel')).toBe('edge');
    expect(apiGetSpy).toHaveBeenCalledWith(expect.stringContaining('channel=edge'));
    expect(document.getElementById('about-version-badge').textContent).toContain('Edge (Rolling)');
    expect(document.getElementById('update-status-title').textContent).toContain('Update Available (Edge): 5c0639d');
    expect(document.getElementById('update-release-notes').textContent).toContain('fix(ci): restore ruff target-version');
    expect(document.getElementById('btn-apply-update-text').textContent).toContain('Install Latest Commit (5c0639d)');
  });

  it('triggers in-app system update when applySystemUpdate is called', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      status: 'restarting',
      auto_restarting: true,
      message: 'Container recreating...',
    });

    // Provide mock last update data
    await setUpdateChannel('edge');
    await applySystemUpdate();

    // Confirm update via custom OS modal
    const okBtn = document.getElementById('confirm-toast-ok');
    if (okBtn) okBtn.click();
    await Promise.resolve();

    expect(postSpy).toHaveBeenCalledWith('/api/system/updates/apply', { channel: 'edge' });
    expect(document.getElementById('update-progress-overlay').style.display).toBe('block');
  });

  it('handles network failure gracefully', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('Network disconnected'));

    await fetchAndRenderSystemAbout();

    expect(document.getElementById('update-status-icon').textContent).toBe('⚠️');
    expect(document.getElementById('update-status-title').textContent).toBe('Unable to check for updates');
    expect(document.getElementById('update-status-desc').textContent).toBe('Network disconnected');
    expect(document.getElementById('btn-check-updates-text').textContent).toBe('Check for Updates');
  });

  it('locks check updates button minWidth and prevents layout shift during checking', async () => {
    const btnCheck = document.getElementById('btn-check-updates');
    Object.defineProperty(btnCheck, 'offsetWidth', { configurable: true, value: 160 });

    vi.spyOn(api, 'get').mockImplementation(async () => {
      expect(parseInt(btnCheck.style.minWidth, 10)).toBeGreaterThanOrEqual(152);
      expect(btnCheck.disabled).toBe(true);
      return { channel: 'stable', update_available: false };
    });

    await fetchAndRenderSystemAbout();
    expect(parseInt(btnCheck.style.minWidth, 10)).toBe(160);
    expect(btnCheck.disabled).toBe(false);
  });
});
