/** UX-35: icons stay out of the translated words; buttons and titles carry them in an aria-hidden span. */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const flush = (ms = 20) => new Promise((r) => setTimeout(r, ms));
const iconAndWords = (el) => [el.querySelector('[aria-hidden="true"]')?.textContent, el.textContent.trim()];

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
  document.body.innerHTML = '';
});

describe('icons apart from the words', () => {
  it('the push and LDAP card titles', async () => {
    document.body.innerHTML = '<div id="push-device-card"></div><div id="sec-ldap-card"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({ enabled: false });
    const { renderPushCard } = await import('../components/push-card.js');
    const { renderLdapPanel } = await import('../components/sso.js');
    await renderPushCard().catch(() => {});
    await renderLdapPanel().catch(() => {});
    expect(iconAndWords(document.querySelector('#push-device-card .kb-title'))).toEqual(['📱', '📱 Notifications on this device']);
    expect(iconAndWords(document.querySelector('#sec-ldap-card .kb-title'))).toEqual(['🏢', '🏢 LDAP / Active Directory']);
  });

  it('a failed backup job', async () => {
    document.body.innerHTML = '<div id="backup-jobs-mount"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({ jobs: [{ id: 'j1', name: 'photos', last_status: 'error', last_error: 'disk full', schedule: 'daily' }] });
    const { fetchAndRenderBackupJobs } = await import('../components/management/backup.js');
    await fetchAndRenderBackupJobs();
    expect(iconAndWords(document.querySelector('.kb-state--crit'))).toEqual(['⚠', '⚠ Failed']);
  });

  it('a model too big for the hardware warns in plain words', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({ hardware_warning: true, warning_message: 'Needs a discrete GPU' });
    const { selectAiRecommendedModel } = await import('../components/management/ai.js');
    await selectAiRecommendedModel('qwen');
    expect(showToast).toHaveBeenCalledWith('Needs a discrete GPU', 'warn');
  });

  it('the card rescan and copy settings buttons come back with their icon', async () => {
    document.body.innerHTML = '<button id="btn-media-rescan"></button><button id="btn-copy-save"></button><div id="management-modal-overlay"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({});
    vi.spyOn(api, 'post').mockResolvedValue({});
    const settings = await import('../components/settings.js');
    settings.initSettings();
    const rescan = document.getElementById('btn-media-rescan');
    const save = document.getElementById('btn-copy-save');
    rescan.click();
    save.click();
    await vi.waitFor(() => expect(iconAndWords(rescan)).toEqual(['🔄', '🔄 Scan']), { timeout: 3000 });
    await vi.waitFor(() => expect(iconAndWords(save)).toEqual(['💾', '💾 Save Configuration']), { timeout: 3500 });
    save.textContent = 'x';
    window.dispatchEvent(new Event('kiboto:lang-changed'));
    expect(iconAndWords(save)).toEqual(['💾', '💾 Save Configuration']);
  });

  it('a VM that fails to start or stop gets its button back', async () => {
    document.body.innerHTML = `
      <div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"></div></div></div>
      <div id="mgmt-vms-summary-strip"></div><div id="mgmt-vms-grid"></div><div id="mgmt-vms-empty"></div><div id="mgmt-vms-kvm-body"></div>`;
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url === '/api/vms' ? [{ id: 'a', name: 'web', state: 'running' }, { id: 'b', name: 'db', state: 'stopped' }] : {},
    );
    vi.spyOn(api, 'post').mockRejectedValue(new Error('busy'));
    const { initManagement } = await import('../components/management.js');
    try { initManagement(); } catch (_) { /* parts of the window this test doesn't build */ }
    window.dispatchEvent(new Event('vm-updated'));
    await flush();
    const start = document.querySelector('.btn-vm-action-start');
    const stop = document.querySelector('.btn-vm-action-stop');
    expect(iconAndWords(start)).toEqual(['▶', '▶ Start']);
    start.click();
    stop.click();
    await vi.waitFor(() => expect(iconAndWords(start)).toEqual(['▶', '▶ Start']));
    await vi.waitFor(() => expect(iconAndWords(stop)).toEqual(['⏹', '⏹ Stop']));
    expect(start.disabled).toBe(false);
  });

  it('the container backup button and the compose file read from disk', async () => {
    const cm = await import('../components/container-modal.js');
    cm._resetContainerModalForTesting();
    cm.initContainerModal();
    const details = {
      cid: 'c1',
      overview: { id: 'c1', full_id: 'c1full', name: 'pihole', image: 'pihole/pihole:2026.10', state: 'running', running: true, network_mode: 'bridge', restart_policy: 'always' },
      resources: {}, ports: [], mounts: [], env: [],
    };
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url.includes('/details') ? details : url.includes('/compose') ? { source: 'disk', compose_yaml: 'services: {disk: 1}', masked_yaml: 'services: {rebuilt: 1}' } : {},
    );
    let done;
    vi.spyOn(api, 'post').mockImplementation(() => new Promise((r) => { done = r; }));
    await cm.openContainerInspector('c1', 'pihole');
    const btn = document.getElementById('ci-btn-backup-action');
    btn.click();
    expect(iconAndWords(btn)).toEqual(['⏳', '⏳ Backing up...']);
    done({ backup: { archive_file: 'pihole.tar.gz' } });
    await vi.waitFor(() => expect(iconAndWords(btn)).toEqual(['💾', '💾 Back up the app now']));
    await cm.switchContainerTab('compose');
    // masked (the default) the file on screen is rebuilt; the badge says so (SET-14)
    await vi.waitFor(() => expect(iconAndWords(document.getElementById('ci-compose-source-badge'))[0]).toBe('✨'));
    const mask = document.getElementById('ci-compose-mask-toggle');
    if (mask) {
      mask.checked = false;
      mask.dispatchEvent(new Event('change'));
      await vi.waitFor(() => expect(iconAndWords(document.getElementById('ci-compose-source-badge'))).toEqual(['📄', '📄 Read from Disk']));
    }
  });
});
