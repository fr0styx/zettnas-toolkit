import { describe, it, expect, vi } from 'vitest';

vi.mock('../i18n.js', () => ({
  t: (key, fallback, params = {}) => String(fallback).replace(/\{(\w+)\}/g, (m, k) => (k in params ? params[k] : m)),
}));

const { showLoadError } = await import('../components/load-error.js');

describe('showLoadError (NUX-14)', () => {
  it('says what failed, is announced, and retries', () => {
    const mount = document.createElement('div');
    const retry = vi.fn();
    showLoadError(mount, new Error('The server is busy.'), retry);
    const box = mount.querySelector('.zn-load-error');
    expect(box.getAttribute('role')).toBe('alert');
    expect(box.textContent).toContain("This couldn't be loaded: The server is busy.");
    mount.querySelector('button').click();
    expect(retry).toHaveBeenCalledOnce();
  });
});
