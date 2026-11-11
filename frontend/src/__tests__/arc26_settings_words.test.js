/** Settings words read in the reader's language: the copy button's state, the security score, the
 * backup passphrase hint, the clock button and the diagnostics counts. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

const { api } = await import('../api.js');
const { showPromptToast } = await import('../toast.js');
const { setLanguage } = await import('../i18n.js');
const { state } = await import('../state.js');
const settings = await import('../components/settings.js');
const { applyDashboardLayout } = await import('../components/mini-preview.js');
const { openDiagnosticsPreviewModal } = await import('../components/management/system.js');

const $ = (id) => document.getElementById(id);
const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  document.body.innerHTML = '';
});
afterEach(async () => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
  await setLanguage('en');
});

describe('settings words', () => {
  it('the copy button state and the security score', async () => {
    document.body.innerHTML = `
      <input type="checkbox" id="btn-copy-toggle"><div id="btn-copy-options"></div><span id="btn-copy-status-text"></span>
      <span id="sec-advisor-score-badge"></span><div id="management-modal-overlay"></div>`;
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/buttons') return { enabled: true };
      if (url === '/api/security/advisor') return { score: 72, checks: [], issues: [] };
      return {};
    });
    vi.spyOn(api, 'post').mockResolvedValue({});
    settings.initSettings();
    await vi.waitFor(() => expect($('btn-copy-status-text').textContent).toBe('ENABLED'));
    await vi.waitFor(() => expect($('sec-advisor-score-badge').textContent).toBe('Score: 72/100'));
    await setLanguage('de');
    const toggle = $('btn-copy-toggle');
    toggle.checked = false;
    toggle.dispatchEvent(new Event('change'));
    expect($('btn-copy-status-text').textContent).toBe('DEAKTIVIERT');
    toggle.checked = true;
    toggle.dispatchEvent(new Event('change'));
    expect($('btn-copy-status-text').textContent).toBe('AKTIVIERT');
  });

  it('a switched-off copy button says so on load', async () => {
    document.body.innerHTML = '<input type="checkbox" id="btn-copy-toggle"><span id="btn-copy-status-text"></span>';
    vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/buttons' ? { enabled: false } : {}));
    settings.initSettings();
    await vi.waitFor(() => expect($('btn-copy-status-text').textContent).toBe('DISABLED'));
  });

  it('the backup passphrase box always asks for a passphrase', async () => {
    document.body.innerHTML = '<button id="btn-backup-download">Download</button><input type="file" id="backup-upload-input">';
    vi.spyOn(api, 'get').mockResolvedValue({});
    settings.initSystemTab();
    $('btn-backup-download').click();
    await vi.waitFor(() => expect(showPromptToast).toHaveBeenCalled());
    // a settings backup is always encrypted (SET-06): the box no longer offers to leave it empty
    expect(showPromptToast.mock.lastCall[5]).toMatchObject({ inputType: 'password', placeholder: 'Backup passphrase' });
    showPromptToast.mock.lastCall[4]();  // cancel
    const upload = $('backup-upload-input');
    const file = new File(['ZETTBAK2rest'], 'nas.zettbak');
    Object.defineProperty(upload, 'files', { value: [file] });
    upload.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(showPromptToast).toHaveBeenCalledTimes(2));
    expect(showPromptToast.mock.lastCall[5].placeholder).toBe('Backup passphrase');
    showPromptToast.mock.lastCall[4]();
    await flush();
  });
});

describe('clock button', () => {
  it('names the clock format in the reader\'s language', async () => {
    document.body.innerHTML = '<div id="screen"></div><div id="dashboard-cards-container"></div><button id="clock-format-btn"></button>';
    state.clockFormat = '12';
    applyDashboardLayout();
    expect($('clock-format-btn').textContent).toBe('12 Hours');
    state.clockFormat = '24';
    applyDashboardLayout();
    expect($('clock-format-btn').textContent).toBe('24 Hours');
  });
});

describe('diagnostics counts', () => {
  const open = (storage, docker) => {
    document.body.innerHTML = `<div id="diagnostics-preview-modal-overlay"><div id="diagnostics-preview-banner"></div>
      <div id="diagnostics-preview-grid"></div><pre id="diagnostics-preview-md"></pre></div>`;
    openDiagnosticsPreviewModal({ executive_status: 'HEALTHY', alerts: [], memory: {}, storage, docker, vms: {} });
    return $('diagnostics-preview-grid').textContent;
  };

  it('counts drives asleep and containers in trouble', () => {
    const grid = open({ disks_count: 1, standby_count: 1, degraded_disks: ['sdb'] }, { restarting: 2, dead: 1 });
    expect(grid).toContain('1 drive (1 asleep)');
    expect(grid).toContain('2 restarting, 1 failed');
  });

  it('shows zeros when the counts are missing', () => {
    const grid = open({}, {});
    expect(grid).toContain('0 drives (0 asleep)');
    expect(grid).toContain('0 restarting, 0 failed');
  });
});
