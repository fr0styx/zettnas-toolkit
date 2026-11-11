/** SET-06 (S17, S19): a waiting settings backup is shown with "Restart now" and "Discard"; the download always asks for a passphrase. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showDangerConfirm: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));
vi.mock('../components/restore-box.js', () => ({ waitForRestart: vi.fn() }));

const { api } = await import('../api.js');
const toast = await import('../toast.js');
const { waitForRestart } = await import('../components/restore-box.js');
const { renderStagedRestore } = await import('../components/settings.js');
const page = readFileSync(resolve(__dirname, '..', 'components/settings.js'), 'utf8');
const html = readFileSync(resolve(__dirname, '..', 'windows/management-window.html'), 'utf8');
const card = () => document.getElementById('restore-staged-card');
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('a settings backup that waits (SET-06)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="restore-staged-card" hidden></div>';
  });

  it('nothing is shown while none waits, or to someone who may not restore', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({ staged: false });
    await renderStagedRestore();
    expect(card().hidden).toBe(true);
    api.get.mockRejectedValueOnce(new Error('Permission denied'));
    await renderStagedRestore();
    expect(card().hidden).toBe(true);
  });

  it('a waiting backup says what it will replace and offers both ways out', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ staged: true, at: 1794300000, files: 12 });
    await renderStagedRestore();
    expect(card().hidden).toBe(false);
    expect(card().textContent).toContain('A settings backup is ready');
    expect(card().textContent).toContain('replaces people, passwords, two-step sign-in, shares and cloud keys');
    expect([...card().querySelectorAll('button')].map((b) => b.textContent)).toEqual(['Restart now', 'Discard']);
  });

  it('"Discard" drops it and the card goes', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValueOnce({ staged: true, at: 1794300000, files: 12 });
    const del = vi.spyOn(api, 'delete').mockResolvedValue({ status: 'ok', discarded: true });
    await renderStagedRestore();
    get.mockResolvedValueOnce({ staged: false });
    card().querySelector('[data-staged="discard"]').click();
    await flush();
    await flush();
    expect(del).toHaveBeenCalledWith('/api/system/restore/staged');
    expect(card().hidden).toBe(true);
  });

  it('"Restart now" restarts and waits for Kiboto to come back', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ staged: true, at: 1794300000, files: 12 });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok', restarting: true });
    await renderStagedRestore();
    card().querySelector('[data-staged="apply"]').click();
    await flush();
    await flush();
    expect(post).toHaveBeenCalledWith('/api/system/restore/apply', {});
    expect(card().textContent).toContain('Kiboto is restarting to apply the backup');
    expect(waitForRestart).toHaveBeenCalled();
  });

  it('where Kiboto cannot restart itself it says who has to', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ staged: true, at: 1794300000, files: 12 });
    vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok', restarting: false });
    await renderStagedRestore();
    card().querySelector('[data-staged="apply"]').click();
    await flush();
    expect(toast.showToast).toHaveBeenCalledWith('Kiboto cannot restart itself here. Restart its container to apply the backup.', 'warn');
    expect(waitForRestart).not.toHaveBeenCalled();
  });

  it('an upload no longer says "Restore successful" and reloads', () => {
    expect(page).not.toContain('Restore successful! Reloading');
    const upload = page.slice(page.indexOf("apiFetch('/api/system/restore'"), page.indexOf("showToast(t('settings.restore_failed'"));
    expect(upload).not.toContain('window.location.reload()');
    expect(upload).toContain('renderStagedRestore();');
  });

  it('the download always asks for a passphrase and always sends it', () => {
    expect(page).not.toContain("await apiFetch('/api/system/backup');");
    expect(page).not.toContain('leave it empty');
    expect(page).toContain("apiFetch('/api/system/backup', { method: 'POST', body: { passphrase } })");
    expect(page).toContain('if (!passphrase) return;');
  });

  it('the card is in the Backup section of Settings', () => {
    const section = html.slice(html.indexOf('id="btn-backup-download"'), html.indexOf('id="btn-backup-download"') + 1800);
    expect(section).toMatch(/<div id="restore-staged-card"[^>]*role="status"[^>]*hidden>/);
  });
});
