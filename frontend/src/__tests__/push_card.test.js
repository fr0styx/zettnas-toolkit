import { describe, it, expect, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

describe('push card (M1)', () => {
  it('decodes the VAPID key to the 65-byte point browsers expect', async () => {
    const { keyBytes } = await import('../components/push-card.js');
    const raw = new Uint8Array(65).map((_, i) => i);
    const b64u = btoa(String.fromCharCode(...raw)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    expect(Array.from(keyBytes(b64u))).toEqual(Array.from(raw));
  });

  it('tells iPhone users to install the app first', async () => {
    const { pushSupport } = await import('../components/push-card.js');
    expect(pushSupport({ navigator: { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0)' } })).toEqual({ ok: false, reason: 'ios-install' });
    expect(pushSupport({ navigator: { serviceWorker: {}, userAgent: 'x' }, PushManager: {}, Notification: {} }).ok).toBe(true);
  });
});
