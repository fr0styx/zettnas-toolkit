/** NUX-20: the About and updates panel says each update state in translatable words, with or without details. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  fetchAndRenderSystemAbout,
  refreshPreviousVersions,
  revertSystemUpdate,
  applySystemUpdate,
  openDiagnosticsPreviewModal,
} from '../components/management/system.js';
import { api } from '../api.js';
import { showConfirmToast, showPromptToast } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const byId = (id) => document.getElementById(id);
const text = (id) => byId(id).textContent;
const PANE = `
  <span id="about-version-badge"></span><span id="about-chassis-model"></span><span id="about-host-platform"></span>
  <span id="about-runtime-env"></span><span id="about-system-uptime"></span>
  <span id="update-status-icon"></span><div id="update-status-title"></div><div id="update-status-desc"></div>
  <span id="update-last-checked"></span>
  <div id="update-details-box"><h4 id="update-release-title"></h4><a id="update-release-link"></a><pre id="update-release-notes"></pre>
    <button id="btn-apply-system-update"><span id="btn-apply-update-text"></span></button></div>
  <div id="update-progress-overlay"><div id="update-progress-title"></div><div id="update-progress-desc"></div></div>
  <button id="btn-revert-system-update"><span id="btn-revert-update-text"></span></button>
  <button id="btn-check-updates"><span id="btn-check-updates-icon"></span><span id="btn-check-updates-text"></span></button>`;

function serve(about, updates) {
  vi.spyOn(api, 'get').mockImplementation(async (url) => {
    if (url === '/api/system/about') return about;
    if (url.startsWith('/api/system/updates/previous')) return { previous: [] };
    if (url.startsWith('/api/system/updates')) {
      if (updates instanceof Error) throw updates;
      return updates;
    }
    return {};
  });
}

describe('updates panel words (NUX-20)', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    document.body.innerHTML = PANE;
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('fills in defaults for a sparse About answer and a bare release', async () => {
    serve({ version: '1.0.0' }, { channel: 'stable', update_available: true, latest_version: '1.1.0' });
    await fetchAndRenderSystemAbout(false, 'stable');
    expect(text('about-chassis-model')).toBe('Standard / DIY');
    expect(text('about-runtime-env')).toBe('Native Host (Python 3.12)');
    expect(text('update-status-title')).toBe('Update Available: v1.1.0');
    expect(text('update-release-title')).toMatch(/^Release/);
    expect(text('update-release-notes')).toBe('No release notes provided.');
    expect(text('btn-apply-update-text')).toBe('Install Release v1.1.0');
  });

  it('describes a tagged release, an up-to-date edge build and a failed check', async () => {
    serve({ containerized: true, python_version: '3.13', chassis_model: 'D8' }, { channel: 'stable', update_available: true, latest_tag: 'v2.0.0', release_name: 'Two', release_notes: 'Notes' });
    await fetchAndRenderSystemAbout(false, 'stable');
    expect(text('about-runtime-env')).toBe('Docker Container (Python 3.13)');
    expect(text('update-status-title')).toBe('Update Available: v2.0.0');
    expect(text('btn-apply-update-text')).toBe('Install Release v2.0.0');

    serve({}, { channel: 'edge', update_available: false });
    await fetchAndRenderSystemAbout(false, 'edge');
    expect(text('update-status-title')).toBe('ZettNAS is up to date with main');
    expect(text('update-status-desc')).toBe('You are running the latest commit on the main branch (latest).');
    serve({}, { channel: 'edge', update_available: false, current_commit: 'abc1234' });
    await fetchAndRenderSystemAbout(false, 'edge');
    expect(text('update-status-desc')).toBe('You are running the latest commit on the main branch (abc1234).');
    serve({}, { channel: 'stable', update_available: false, current_version: '2.0.0' });
    await fetchAndRenderSystemAbout(false, 'stable');
    expect(text('update-status-desc')).toBe('You are running the latest stable release (v2.0.0).');

    serve({}, new Error(''));
    await fetchAndRenderSystemAbout(false, 'stable');
    expect(text('update-status-desc')).toBe('Offline or network request failed.');
    serve({}, new Error('rate limited'));
    await fetchAndRenderSystemAbout(false, 'stable');
    expect(text('update-status-desc')).toBe('rate limited');
  });

  it('names the version a revert goes back to', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ previous: [{ id: 's1', version: '1.9.0', image_available: true }] });
    await refreshPreviousVersions();
    expect(text('btn-revert-update-text')).toBe('Revert to v1.9.0');
    get.mockResolvedValue({ previous: [{ id: 's2', image_available: true }] });
    await refreshPreviousVersions();
    expect(text('btn-revert-update-text')).toBe('Revert to previous version');

    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    await revertSystemUpdate();
    const [, , , onOk, , opts] = showPromptToast.mock.calls.at(-1);
    expect(opts).toMatchObject({ okText: 'Revert', placeholder: 'Your password' });
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce(undefined);
    await onOk('pw');
    expect(text('update-progress-title')).toBe('Reverting to the previous version...');
    expect(text('update-progress-desc')).toBe('Restoring the previous version and reconnecting...');
    post.mockResolvedValueOnce({ message: 'Going back' });
    await onOk('pw');
    expect(text('update-progress-desc')).toBe('Going back');
    vi.clearAllTimers();
    vi.unstubAllGlobals();
  });

  it('says what to do when an update downloads but does not restart', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    const post = vi.spyOn(api, 'post').mockResolvedValue({ auto_restarting: false });
    await applySystemUpdate();
    const onOk = showConfirmToast.mock.calls.at(-1)[2];
    await onOk();
    expect(byId('update-progress-desc').textContent).toBe('Latest image downloaded.Please restart the container in Unraid or Docker to finalize.');
    post.mockResolvedValue({ auto_restarting: false, message: 'Pulled.' });
    await onOk();
    expect(byId('update-progress-desc').textContent).toContain('Pulled.');
    post.mockResolvedValue({});
    await onOk();
    expect(text('update-progress-desc')).toBe('Restarting container and reconnecting...');
    post.mockResolvedValue({ message: 'Restarting now' });
    await onOk();
    expect(text('update-progress-desc')).toBe('Restarting now');
    vi.clearAllTimers();
    vi.unstubAllGlobals();
  });

  it('says when the diagnostics summary is empty', () => {
    document.body.innerHTML = '<div id="diagnostics-preview-modal-overlay"><div class="smart-modal-window"></div></div><pre id="diagnostics-preview-md"></pre>';
    openDiagnosticsPreviewModal({});
    expect(text('diagnostics-preview-md')).toBe('No summary generated.');
    openDiagnosticsPreviewModal({ support_markdown: '# Report' });
    expect(text('diagnostics-preview-md')).toBe('# Report');
  });
});
