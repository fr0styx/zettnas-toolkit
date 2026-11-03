/** ARC-26 / NUX-20: fan curve presets: save, apply, delete, in the reader's language. */
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';

const { api } = await import('../api.js');
const { ZettEventBus } = await import('../event-bus.js');
const { setLanguage } = await import('../i18n.js');
const { initFanControl } = await import('../components/fan-control.js');

const byId = (id) => document.getElementById(id);
const toasts = [];
ZettEventBus.on('toast', (t) => toasts.push(t));
const lastToast = () => toasts.at(-1);

describe('fan presets', () => {
  beforeAll(async () => {
    document.body.innerHTML = `
      <select id="fan-preset-select"></select>
      <button id="btn-save-fan-preset"></button><button id="btn-apply-fan-preset"></button><button id="btn-delete-fan-preset"></button>
      <div id="fan-preset-modal-overlay"><input id="fan-preset-name-input">
        <button id="fan-preset-submit-btn"></button><button id="fan-preset-cancel-btn"></button><button id="fan-preset-close-btn"></button></div>
      <div id="fan-preset-delete-overlay"><span id="fan-delete-preset-target"></span>
        <button id="fan-delete-confirm-btn"></button><button id="fan-delete-cancel-btn"></button><button id="fan-delete-close-btn"></button></div>`;
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url === '/api/fans/presets' ? { presets: { Quiet: {}, Loud: {} } } : { profile: 'auto', curve_points: [[30, 30], [60, 100]] },
    );
    initFanControl();
    await vi.waitFor(() => expect(byId('fan-preset-select').options).toHaveLength(3));
  });
  beforeEach(() => {
    toasts.length = 0;
  });

  it('applies the chosen preset', async () => {
    const sel = byId('fan-preset-select');
    expect(byId('btn-apply-fan-preset').disabled).toBe(true);
    sel.value = 'Quiet';
    sel.dispatchEvent(new Event('change'));
    expect(byId('btn-apply-fan-preset').disabled).toBe(false);
    expect(byId('btn-delete-fan-preset').style.display).toBe('inline-flex');
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ fan_config: { profile: 'curve', curve_points: [[30, 20], [60, 90]] } });
    byId('btn-apply-fan-preset').click();
    await vi.waitFor(() => expect(lastToast()).toEqual({ message: 'Preset "Quiet" applied', type: 'success' }));
    expect(post).toHaveBeenCalledWith('/api/fans/presets/Quiet/apply');
    post.mockRejectedValueOnce(new Error('busy'));
    byId('btn-apply-fan-preset').click();
    await vi.waitFor(() => expect(lastToast()).toEqual({ message: 'Failed to apply preset: busy', type: 'error' }));
    post.mockRejectedValueOnce('offline');
    byId('btn-apply-fan-preset').click();
    await vi.waitFor(() => expect(lastToast()).toEqual({ message: 'Failed to apply preset: offline', type: 'error' }));
  });

  it('saves a preset under a name, and needs one', async () => {
    byId('btn-save-fan-preset').click();
    expect(byId('fan-preset-modal-overlay').classList.contains('open')).toBe(true);
    const input = byId('fan-preset-name-input');
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    expect(input.style.borderColor).toContain('--crit');
    input.dispatchEvent(new Event('input'));
    input.value = 'Night';
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({});
    byId('fan-preset-submit-btn').click();
    await vi.waitFor(() => expect(lastToast()).toEqual({ message: 'Preset "Night" saved', type: 'success' }));
    expect(post.mock.calls.at(-1)[0]).toBe('/api/fans/presets');
    expect(byId('fan-preset-modal-overlay').style.display).toBe('none');

    byId('btn-save-fan-preset').click();
    input.value = 'Night';
    post.mockRejectedValueOnce(new Error('full'));
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await vi.waitFor(() => expect(lastToast()).toEqual({ message: 'Failed to save preset: full', type: 'error' }));
    post.mockRejectedValueOnce('locked');
    byId('fan-preset-submit-btn').click();
    await vi.waitFor(() => expect(lastToast()).toEqual({ message: 'Failed to save preset: locked', type: 'error' }));
    for (const close of ['fan-preset-cancel-btn', 'fan-preset-close-btn']) {
      byId('btn-save-fan-preset').click();
      byId(close).click();
      expect(byId('fan-preset-modal-overlay').classList.contains('open')).toBe(false);
    }
    byId('btn-save-fan-preset').click();
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(byId('fan-preset-modal-overlay').classList.contains('open')).toBe(false);
  });

  it('deletes a preset after asking, in German too', async () => {
    const sel = byId('fan-preset-select');
    sel.value = 'Loud';
    sel.dispatchEvent(new Event('change'));
    byId('btn-delete-fan-preset').click();
    expect(byId('fan-delete-preset-target').textContent).toBe('"Loud"');
    const del = vi.spyOn(api, 'delete').mockResolvedValueOnce({});
    byId('fan-delete-confirm-btn').click();
    await vi.waitFor(() => expect(lastToast()).toEqual({ message: 'Preset "Loud" deleted', type: 'info' }));
    expect(del).toHaveBeenCalledWith('/api/fans/presets/Loud');

    await setLanguage('de');
    try {
      sel.value = 'Quiet';
      sel.dispatchEvent(new Event('change'));
      byId('btn-delete-fan-preset').click();
      del.mockRejectedValueOnce(new Error('gesperrt'));
      byId('fan-delete-confirm-btn').click();
      await vi.waitFor(() => expect(lastToast()).toEqual({ message: 'Das Profil konnte nicht gelöscht werden: gesperrt', type: 'error' }));
      del.mockRejectedValueOnce('offline');
      byId('fan-delete-confirm-btn').click();
      await vi.waitFor(() => expect(lastToast().message).toBe('Das Profil konnte nicht gelöscht werden: offline'));
    } finally {
      await setLanguage('en');
    }
    for (const close of ['fan-delete-cancel-btn', 'fan-delete-close-btn']) {
      byId('btn-delete-fan-preset').click();
      byId(close).click();
      expect(byId('fan-preset-delete-overlay').classList.contains('open')).toBe(false);
    }
    byId('btn-delete-fan-preset').click();
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(byId('fan-preset-delete-overlay').classList.contains('open')).toBe(false);
  });
});
