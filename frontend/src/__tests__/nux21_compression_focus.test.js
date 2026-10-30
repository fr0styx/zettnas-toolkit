import { describe, it, expect, vi } from 'vitest';

vi.mock('../i18n.js', () => ({
  t: (key, fallback, params = {}) => String(fallback).replace(/\{(\w+)\}/g, (m, k) => (k in params ? params[k] : m)),
}));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('../api.js', () => ({
  api: { get: vi.fn(async () => ({ value: 'zstd:3', supported: true, choices: ['zstd', 'lz4', 'off'] })), put: vi.fn() },
}));

const { openShareCompression, trapKeys } = await import('../components/share-compression.js');

describe('compression dialog focus (NUX-21)', () => {
  it('moves focus in, keeps Tab inside, and gives it back on Esc', async () => {
    const opener = document.createElement('button');
    document.body.append(opener);
    opener.focus();
    const host = await openShareCompression('photos');
    const select = host.querySelector('select');
    expect(document.activeElement).toBe(select);
    const items = [...host.querySelectorAll('button, select')];
    items[items.length - 1].focus();
    const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    host.dispatchEvent(tab);
    expect(document.activeElement).toBe(items[0]);
    host.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(host.style.display).toBe('none');
    expect(document.activeElement).toBe(opener);
  });

  it('ignores other keys', () => {
    const close = vi.fn();
    trapKeys(document.createElement('div'), new KeyboardEvent('keydown', { key: 'a' }), close);
    expect(close).not.toHaveBeenCalled();
  });
});
