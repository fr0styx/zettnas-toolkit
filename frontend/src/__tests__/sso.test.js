import { describe, it, expect, vi, beforeEach } from 'vitest';

const puts = [];
vi.mock('../api.js', () => ({
  api: {
    get: vi.fn(async () => ({ enabled: false, issuer: '', client_id: '', client_secret: '', label: 'Single sign-on', admin_groups: [], public_url: '', redirect_uri: 'http://nas/api/auth/oidc/callback' })),
    put: vi.fn(async (...a) => puts.push(a)),
  },
}));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

describe('single sign-on (M6)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<button id="login-sso-btn" hidden></button><p id="login-sso-error" hidden></p><div id="sec-sso-card"></div>';
    puts.length = 0;
  });

  it('shows the provider button and a returned error', async () => {
    globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => ({ enabled: true, label: 'Authentik' }) }));
    const { initSsoLogin } = await import('../components/sso.js');
    const replaceState = vi.fn();
    await initSsoLogin({ location: { search: '?sso_error=expired', pathname: '/' }, history: { replaceState } });
    expect(document.getElementById('login-sso-btn').hidden).toBe(false);
    expect(document.getElementById('login-sso-btn').textContent).toContain('Authentik');
    expect(document.getElementById('login-sso-error').textContent).toBe('expired');
    expect(replaceState).toHaveBeenCalledWith(null, '', '/');
  });

  it('saves settings with groups as a list and shows the redirect URI', async () => {
    const { renderSsoPanel } = await import('../components/sso.js');
    await renderSsoPanel();
    const card = document.getElementById('sec-sso-card');
    expect(card.textContent).toContain('http://nas/api/auth/oidc/callback');
    card.querySelector('input[name="issuer"]').value = 'https://auth.example.com/app';
    card.querySelector('input[name="admin_groups"]').value = 'nas-admins, it';
    card.querySelector('form').dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(puts.length).toBe(1));
    expect(puts[0][1].admin_groups).toEqual(['nas-admins', 'it']);
    expect(puts[0][1].issuer).toBe('https://auth.example.com/app');
  });
});
