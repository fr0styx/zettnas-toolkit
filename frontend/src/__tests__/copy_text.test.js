import { describe, it, expect, vi, afterEach } from 'vitest';
import { copyText } from '../utils.js';

// A NAS is often opened over plain HTTP, where browsers hide navigator.clipboard
describe('copyText', () => {
  afterEach(() => {
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true });
    delete document.execCommand;
  });

  it('copies through a hidden text box on plain HTTP', async () => {
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true });
    let copied = '';
    document.execCommand = vi.fn(() => {
      copied = document.activeElement.value;
      return true;
    });
    await copyText('/mnt/user/vault/a.jpg');
    expect(copied).toBe('/mnt/user/vault/a.jpg');
    expect(document.querySelector('textarea')).toBeNull();
  });

  it('throws when nothing could be copied', async () => {
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true });
    document.execCommand = vi.fn(() => false);
    await expect(copyText('x')).rejects.toThrow('Copy failed');
  });

  it('uses the clipboard API on secure pages', async () => {
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true });
    const writeText = vi.fn(async () => {});
    Object.assign(navigator, { clipboard: { writeText } });
    await copyText('hello');
    expect(writeText).toHaveBeenCalledWith('hello');
  });
});
