import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { describeValue, ratioText, compressionBody, openShareCompression } from '../components/share-compression.js';

describe('share compression (FEAT-15)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('names the setting and the savings', () => {
    expect(describeValue('off')).toBe('Off');
    expect(describeValue('')).toBe('Off');
    expect(describeValue('zstd:3')).toBe('zstd (level 3)');
    expect(describeValue('lz4')).toBe('lz4');
    expect(ratioText(2)).toContain('50%');
    expect(ratioText(1)).toBe('Nothing saved yet');
    expect(ratioText(null)).toBe('');
  });

  it('offers the choices with the current one selected', () => {
    const body = compressionBody('media', { supported: true, value: 'zstd:3', choices: ['off', 'zstd', 'lzo', 'zlib'], ratio: null, from_mount: true });
    const select = body.querySelector('select');
    expect([...select.options].map((o) => o.value)).toEqual(['off', 'zstd', 'lzo', 'zlib']);
    expect(select.value).toBe('zstd');
    expect(body.textContent).toContain('zstd (level 3)');
  });

  it('shows why when it cannot be set', () => {
    const ro = compressionBody('media', { supported: true, read_only: true, value: 'lz4', choices: ['off'], reason: 'Set compression in unraid\'s own settings' });
    expect(ro.querySelector('form')).toBeNull();
    expect(ro.textContent).toContain('unraid');
    const none = compressionBody('x', { supported: false, value: 'off', choices: [] });
    expect(none.textContent).toContain('no compression');
    const asleep = compressionBody('x', { supported: true, asleep: true, value: 'zstd', choices: ['off', 'zstd'] });
    expect(asleep.textContent).toContain('asleep');
  });

  it('loads, saves and redraws', async () => {
    api.get.mockResolvedValue({ supported: true, value: 'lz4', ratio: 1.5, choices: ['off', 'lz4', 'zstd'] });
    api.put.mockResolvedValue({ supported: true, value: 'zstd', ratio: 1.5, choices: ['off', 'lz4', 'zstd'] });
    const host = await openShareCompression('my share');
    expect(api.get).toHaveBeenCalledWith('/api/storage/shares/my%20share/compression');
    const form = host.querySelector('form');
    form.elements.value.value = 'zstd';
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalled());
    expect(api.put).toHaveBeenCalledWith('/api/storage/shares/my%20share/compression', { value: 'zstd' });
    expect(host.textContent).toContain('Now: zstd');
    host.querySelector('[data-close]').click();
    expect(host.style.display).toBe('none');
  });

  it('shows an error from the server', async () => {
    api.get.mockRejectedValue(new Error('No share named x'));
    const host = await openShareCompression('x');
    expect(host.textContent).toContain('No share named x');
  });
});
