import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('qrcode', () => ({ default: { toString: vi.fn(async (text) => `<svg data-text="${text}"></svg>`) } }));
const { api } = await import('../api.js');
const ra = await import('../components/remote-access.js');

const LOGIN = { state: 'NeedsLogin', auth_url: 'https://login.tailscale.com/a/abc' };

describe('SET-16 stage 2: the sign-in wait', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('keeps waiting while the same sign-in link is open', async () => {
    const card = document.createElement('div');
    document.body.append(card);
    api.get.mockResolvedValue(LOGIN);
    expect(await ra.signInDone(card, LOGIN)).toBe(false);
    expect(card.children.length).toBe(0);
  });

  it('draws the card again once Tailscale moved on or gave a new link', async () => {
    const card = document.createElement('div');
    document.body.append(card);
    api.get.mockResolvedValue({ ...LOGIN, auth_url: 'https://login.tailscale.com/a/new' });
    expect(await ra.signInDone(card, LOGIN)).toBe(true);
    expect(card.querySelector('a[target="_blank"]').getAttribute('href')).toBe('https://login.tailscale.com/a/new');
  });

  it('stops asking once the window is closed', async () => {
    vi.useFakeTimers();
    const win = document.createElement('div');
    const card = document.createElement('div');
    win.append(card);
    document.body.append(win);
    api.get.mockResolvedValue(LOGIN);
    await ra.renderRemoteAccess(card, LOGIN);
    const before = api.get.mock.calls.length;
    win.hidden = true;
    await vi.advanceTimersByTimeAsync(30000);
    expect(api.get.mock.calls.length).toBe(before);
  });
});
