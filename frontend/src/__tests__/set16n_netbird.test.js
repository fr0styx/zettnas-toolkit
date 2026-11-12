/** SET-16N: NetBird on the "Use from anywhere" card. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api } from '../api.js';

const ra = await import('../components/remote-access.js');

describe('NetBird on the card', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('reads the key and server only when NetBird is chosen', () => {
    document.body.innerHTML = '<form id="f"><input name="remote-kind" type="radio" value="netbird" checked><input name="setup_key" value=" abc-key "><input name="management_url" value=" https://nb.example.com "></form>';
    expect(ra.netbirdBody(document.getElementById('f'))).toEqual({ setup_key: 'abc-key', management_url: 'https://nb.example.com' });
    document.body.innerHTML = '<form id="f"><input name="remote-kind" type="radio" value="tailscale" checked></form>';
    expect(ra.netbirdBody(document.getElementById('f'))).toBeNull();
  });

  it('shows the NetBird address when Tailscale is not running, Tailscale first otherwise', async () => {
    const nb = { state: 'Connected', ip: '100.92.1.5', name: 'kiboto.netbird.cloud', peers_connected: 2 };
    const body = await ra.remoteBody({ state: 'Stopped' }, nb);
    expect(body.textContent).toContain('kiboto.netbird.cloud');
    expect(body.textContent).toContain('2 devices connected');
    expect(body.querySelector('[data-netbird="disconnect"]')).toBeTruthy();
    const form = await ra.remoteBody({ state: 'Stopped' }, { state: 'Disconnected' });
    expect(form.querySelector('input[value="netbird"]')).toBeTruthy();
  });

  it('connects through NetBird from the form, and disconnects', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation(async (url) => (url.endsWith('/netbird') ? { state: 'Disconnected' } : { state: 'Stopped' }));
    const post = vi.spyOn(api, 'post').mockResolvedValue({ state: 'Connected' });
    const card = document.createElement('div');
    document.body.replaceChildren(card);
    await ra.renderRemoteAccess(card);
    const form = card.querySelector('[data-remote-form]');
    form.querySelector('input[value="netbird"]').checked = true;
    form.querySelector('input[name="setup_key"]').value = 'key-1234567890-abcdef';
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/network/remote-access/netbird/connect', { setup_key: 'key-1234567890-abcdef', management_url: '' }));
    get.mockImplementation(async (url) => (url.endsWith('/netbird') ? { state: 'Connected', ip: '100.92.1.5', name: 'nas' } : { state: 'Stopped' }));
    await ra.renderRemoteAccess(card);
    card.querySelector('[data-netbird="disconnect"]').click();
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/network/remote-access/netbird/disconnect', {}));
  });
});
