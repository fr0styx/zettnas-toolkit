import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('qrcode', () => ({ default: { toString: vi.fn(async (text) => `<svg data-text="${text}"></svg>`) } }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const ra = await import('../components/remote-access.js');

const RUNNING = {
  state: 'Running',
  name: 'zettnas.tail1234.ts.net',
  ips: ['100.101.102.103'],
  https: true,
  login_server: '',
  addresses: { zettnas: 'http://zettnas.tail1234.ts.net:8082/', immich: 'http://zettnas.tail1234.ts.net:2283/' },
};

async function mounted(status) {
  const mount = document.createElement('div');
  document.body.appendChild(mount);
  api.get.mockResolvedValue(status);
  await ra.installRemoteAccess(mount);
  return mount;
}

describe('COMP-01: use from anywhere', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('offers Tailscale first, and Headscale with its address and key', async () => {
    const mount = await mounted({ state: 'NotInstalled' });
    const form = /** @type {HTMLFormElement} */ (mount.querySelector('[data-remote-form]'));
    const own = /** @type {HTMLElement} */ (mount.querySelector('.remote-own'));
    expect(own.hidden).toBe(true);
    expect(ra.connectBody(form)).toEqual({ login_server: '', auth_key: '' });
    /** @type {HTMLInputElement} */ (form.querySelector('[value="headscale"]')).checked = true;
    form.dispatchEvent(new Event('change', { bubbles: true }));
    expect(own.hidden).toBe(false);
    /** @type {HTMLInputElement} */ (form.querySelector('[name="login_server"]')).value = ' https://hs.example.com ';
    /** @type {HTMLInputElement} */ (form.querySelector('[name="auth_key"]')).value = 'key1';
    expect(ra.connectBody(form)).toEqual({ login_server: 'https://hs.example.com', auth_key: 'key1' });
  });

  it('shows the sign-in link as a QR code after Connect, and the addresses once signed in', async () => {
    vi.useFakeTimers();
    const mount = await mounted({ state: 'Stopped' });
    const login = { state: 'NeedsLogin', auth_url: 'https://login.tailscale.com/a/abc' };
    api.post.mockResolvedValue(login);
    mount.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(mount.querySelector('.remote-qr svg')).not.toBeNull());
    expect(api.post).toHaveBeenCalledWith('/api/network/remote-access/connect', { login_server: '', auth_key: '' });
    expect(mount.querySelector('.remote-qr svg').getAttribute('data-text')).toBe(login.auth_url);
    expect(mount.querySelector('a[target="_blank"]').getAttribute('href')).toBe(login.auth_url);
    api.get.mockResolvedValue(RUNNING);
    await vi.advanceTimersByTimeAsync(3100);
    await vi.waitFor(() => expect(mount.textContent).toContain('zettnas.tail1234.ts.net:8082'));
    expect(mount.querySelector('.remote-qr svg').getAttribute('data-text')).toBe(RUNNING.addresses.zettnas);
    expect(mount.textContent).toContain(RUNNING.addresses.immich);
  });

  it('turns on HTTPS with the port this page uses, and opens the page to allow it', async () => {
    const mount = await mounted(RUNNING);
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    api.post.mockResolvedValue({ ...RUNNING, approval_url: 'https://login.tailscale.com/f/serve?node=1' });
    /** @type {HTMLElement} */ (mount.querySelector('[data-remote="publish"]')).click();
    await vi.waitFor(() => expect(open).toHaveBeenCalledWith('https://login.tailscale.com/f/serve?node=1', '_blank', 'noopener'));
    expect(api.post).toHaveBeenCalledWith('/api/network/remote-access/publish', { app_port: ra.appPort() });
    expect(toast.showToast).toHaveBeenCalled();
  });

  it('hides "Turn on HTTPS" once the address is https, and explains Headscale', async () => {
    let mount = await mounted({ ...RUNNING, addresses: { zettnas: 'https://zettnas.tail1234.ts.net/' } });
    expect(mount.querySelector('[data-remote="publish"]')).toBeNull();
    document.body.innerHTML = '';
    mount = await mounted({ ...RUNNING, https: false, login_server: 'https://hs.example.com' });
    expect(mount.textContent).toContain('Headscale gives no HTTPS certificates');
    document.body.innerHTML = '';
    mount = await mounted({ ...RUNNING, https: false });
    expect(mount.textContent).toContain('MagicDNS and HTTPS certificates');
  });

  it('lists every app and offers HTTPS for one installed later (NFEAT-5)', async () => {
    const zettnas = 'https://zettnas.tail1234.ts.net/';
    const apps = [
      { name: 'jellyfin', url: 'https://zettnas.tail1234.ts.net:18096/' },
      { name: 'paperless', url: 'http://zettnas.tail1234.ts.net:8000/' },
    ];
    let mount = await mounted({ ...RUNNING, addresses: { zettnas, apps } });
    // the apps are folded away under one line, as links named after the app with their port
    const fold = mount.querySelector('details.remote-apps');
    expect(fold.querySelector('summary').textContent).toBe('2 apps on your tailnet');
    const links = [...fold.querySelectorAll('a')].map((a) => [a.textContent, a.getAttribute('href')]);
    expect(links).toEqual([
      ['jellyfin', 'https://zettnas.tail1234.ts.net:18096/'],
      ['paperless', 'http://zettnas.tail1234.ts.net:8000/'],
    ]);
    expect(fold.textContent).toContain(':18096');
    fold.open = true;
    fold.dispatchEvent(new Event('toggle'));
    expect(localStorage.getItem('kiboto_remote_apps_open')).toBe('1');
    expect(mount.querySelector('[data-remote="publish"]').textContent).toBe('Turn on HTTPS for new apps');
    document.body.innerHTML = '';
    mount = await mounted({ ...RUNNING, addresses: { zettnas, apps: apps.slice(0, 1) } });
    expect(mount.querySelector('[data-remote="publish"]')).toBeNull();
  });

  it('reports a failed connect and stays hidden without the API', async () => {
    const mount = await mounted({ state: 'Stopped' });
    api.post.mockRejectedValue(new Error('Tailscale could not start.'));
    mount.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(toast.showToast).toHaveBeenCalledWith('Tailscale could not start.', 'error'));
    api.post.mockResolvedValue({ state: 'Stopped' });
    document.body.innerHTML = '';
    const m2 = await mounted(RUNNING);
    api.post.mockResolvedValue({ state: 'Stopped' });
    /** @type {HTMLElement} */ (m2.querySelector('[data-remote="disconnect"]')).click();
    await vi.waitFor(() => expect(m2.querySelector('[data-remote-form]')).not.toBeNull());
    document.body.innerHTML = '';
    const card = document.createElement('div');
    api.get.mockRejectedValue(new Error('403'));
    await ra.renderRemoteAccess(card);
    expect(card.hidden).toBe(true);
  });

  it('knows the port of this page', () => {
    expect(ra.appPort({ port: '8082', protocol: 'http:' })).toBe(8082);
    expect(ra.appPort({ port: '', protocol: 'https:' })).toBe(443);
    expect(ra.appPort({ port: '', protocol: 'http:' })).toBe(80);
  });

  it('labels ports and keeps the main addresses as links', async () => {
    const { portLabel, addressesView } = await import('../components/remote-access.js');
    expect(portLabel('http://a.ts.net:2283/')).toBe(':2283');
    expect(portLabel('https://a.ts.net/')).toBe('');
    expect(portLabel('not a url')).toBe('');
    const view = addressesView({ kiboto: 'https://a.ts.net/', immich: 'https://a.ts.net:8443/' }, false);
    expect([...view.querySelectorAll('.remote-addresses a')].map((a) => a.getAttribute('href'))).toEqual(['https://a.ts.net/', 'https://a.ts.net:8443/']);
    expect(view.querySelector('details')).toBeNull();
  });
});
