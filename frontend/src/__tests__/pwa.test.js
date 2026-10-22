import { describe, it, expect, vi } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

describe('PWA share sheet (M1)', () => {
  it('reports how many shared files reached the Inbox', async () => {
    const { sharedResultMessage } = await import('../pwa.js');
    expect(sharedResultMessage(new URLSearchParams('shared=3&failed=0')).text).toContain('3');
    expect(sharedResultMessage(new URLSearchParams('shared=2&failed=1')).type).toBe('warn');
    expect(sharedResultMessage(new URLSearchParams('shared=login')).text).toMatch(/Sign in/);
    expect(sharedResultMessage(new URLSearchParams('x=1'))).toBeNull();
  });

  it('registers the service worker and cleans the address bar', async () => {
    const { initPwa } = await import('../pwa.js');
    const { showToast } = await import('../toast.js');
    const register = vi.fn(() => Promise.resolve());
    const replaceState = vi.fn();
    initPwa({
      navigator: { serviceWorker: { register } },
      location: { protocol: 'https:', search: '?shared=1&failed=0&lang=de', pathname: '/', hash: '' },
      history: { replaceState },
    });
    expect(register).toHaveBeenCalledWith('/sw.js');
    expect(showToast).toHaveBeenCalled();
    expect(replaceState).toHaveBeenCalledWith(null, '', '/?lang=de');
  });

  it('declares a share target in the manifest', async () => {
    const fs = await import('node:fs');
    const m = JSON.parse(fs.readFileSync('frontend/public/manifest.json', 'utf8'));
    expect(m.share_target.action).toBe('/share-target');
    expect(m.share_target.params.files[0].name).toBe('files');
    expect(m.icons.some((i) => i.sizes === '512x512')).toBe(true);
  });
});
