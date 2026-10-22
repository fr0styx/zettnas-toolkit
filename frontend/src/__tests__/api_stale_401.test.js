// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api, auth } from '../api.js';

describe('stale 401 after sign-in', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    auth.clearToken();
  });

  it('keeps the new session when a request sent before login comes back 401', async () => {
    let release;
    vi.spyOn(window, 'fetch').mockImplementation(
      () => new Promise((resolve) => { release = () => resolve(new Response('{}', { status: 401 })); }),
    );
    const pending = api.get('/api/fans').catch((e) => e);
    auth.setToken('ignored-cookie-session');
    release();
    const err = await pending;
    expect(err.status).toBe(401);
    expect(auth.hasToken()).toBe(true);
    expect(window.localStorage.getItem('zettnas_signed_in')).toBe('1');
  });

  it('still signs out on a 401 for a request sent after login', async () => {
    auth.setToken('x');
    vi.spyOn(window, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }));
    await api.get('/api/fans').catch(() => {});
    expect(window.localStorage.getItem('zettnas_signed_in')).toBe(null);
  });
});
