/** SET-07 (S22): "Clean up" leaves stopped apps alone unless asked, names them, and asks again. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { showStoppedApps, askRemoveStopped } from '../components/management/docker.js';
import { showDangerConfirm } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showDangerConfirm: vi.fn(),
  showBottomSheet: vi.fn(),
  showPromptToast: vi.fn(),
}));

const src = readFileSync(resolve(__dirname, '..', 'components/management/docker.js'), 'utf8');
const byId = (id) => document.getElementById(id);

describe('"Clean up" and stopped apps (SET-07)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<input type="checkbox" id="dpm-opt-containers"><strong id="dpm-opt-containers-title"></strong><div id="dpm-opt-containers-desc"></div>';
  });

  it('the option starts unticked', () => {
    expect(src).toContain('<input class="dkd-x-5" type="checkbox" id="dpm-opt-containers">');
    expect(src).not.toContain('id="dpm-opt-containers" checked');
  });

  it('names the apps it would remove', () => {
    showStoppedApps(['paperless', 'immich_backup_1790000000']);
    expect(byId('dpm-opt-containers-title').textContent).toBe('Remove 2 stopped apps');
    expect(byId('dpm-opt-containers-desc').textContent).toContain('paperless, immich_backup_1790000000');
    expect(byId('dpm-opt-containers').disabled).toBe(false);
    expect(byId('dpm-opt-containers').checked).toBe(false);
  });

  it('with every app running there is nothing to tick', () => {
    byId('dpm-opt-containers').checked = true;
    showStoppedApps([]);
    expect(byId('dpm-opt-containers').disabled).toBe(true);
    expect(byId('dpm-opt-containers').checked).toBe(false);
    expect(byId('dpm-opt-containers-desc').textContent).toBe('Every app is running: nothing to remove.');
  });

  it('asks again, by name, before it removes them', async () => {
    showDangerConfirm.mockImplementationOnce((title, msg, yes) => yes());
    expect(await askRemoveStopped(['paperless'])).toBe(true);
    const [title, msg, , , options] = showDangerConfirm.mock.calls[0];
    expect(title).toBe('Remove 1 stopped app?');
    expect(msg).toContain('removed for good: paperless.');
    expect(msg).toContain('Their folders stay');
    expect(options.okText).toBe('Remove them');
    showDangerConfirm.mockImplementationOnce((title, msg, yes, no) => no());
    expect(await askRemoveStopped(['paperless'])).toBe(false);
  });

  it('the start button sends "remove stopped apps" only after that question', () => {
    const start = src.slice(src.indexOf('confirmBtn.onclick = async () => {'), src.indexOf("followPruneJob(res.job);"));
    expect(start).toContain('if (removeStopped && !(await askRemoveStopped(_stoppedApps))) return;');
    expect(start).toContain('prune_containers: removeStopped,');
  });
});
