import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('qrcode', () => ({ default: { toString: vi.fn(async (text) => `<svg data-text="${text}"></svg>`) } }));
const { api } = await import('../api.js');
const ex = await import('../components/exposure-line.js');
const ra = await import('../components/remote-access.js');

describe('SET-24: what reaches the NAS from outside', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('says closed, private or public in one sentence', () => {
    expect(ex.exposureText({ level: 'off', tone: 'neutral' }).sentence).toBe('Through Kiboto, nothing reaches this NAS from outside.');
    expect(ex.exposureText({ level: 'private', via: ['tailscale'] }).sentence).toContain('Tailscale network');
    expect(ex.exposureText({ level: 'private', via: ['netbird'] }).sentence).toContain('NetBird network');
    const pub = ex.exposureText({ level: 'public', share_links: true, apps: 2, unexpected: [443], tone: 'red', reason: 'unexpected_public' });
    expect(pub.sentence).toBe('On the internet: share links, 2 apps, 1 other port.');
    expect(pub.word).toBe('Public');
    expect(pub.tone).toBe('red');
    expect(pub.notes[0]).toBe('Kiboto did not put port 443 on the internet. Check it in Tailscale.');
  });

  it('counts one and many, and says why it is amber', () => {
    expect(ex.publicParts({ apps: 1, unexpected: [1, 2] })).toBe('1 app, 2 other ports');
    expect(ex.publicParts({})).toBe('');
    expect(ex.exposureText({ level: 'private', via: ['tailscale'], reason: 'sign_in' }).notes[0]).toBe('Tailscale needs you to sign in again.');
    expect(ex.exposureText({ level: 'private', via: ['tailscale'], reason: 'key_expiring', key_days: 3 }).notes[0]).toBe("This NAS's Tailscale sign-in runs out in 3 days.");
    expect(ex.exposureText({ level: 'private', via: ['tailscale'], reason: 'key_expiring', key_days: 0 }).notes[0]).toBe("This NAS's Tailscale sign-in runs out today.");
    const unchecked = ex.exposureText({ level: 'private', via: ['tailscale'], checked: false });
    expect(unchecked.notes).toContain("Kiboto couldn't ask Tailscale what is public.");
    expect(unchecked.notes.at(-1)).toContain('reverse proxy');
    expect(ex.exposureText({ level: 'weird' }).icon).toBe('🔒');
  });

  it('draws the line above the card, and hides it when the server fails', async () => {
    const mount = document.createElement('div');
    document.body.append(mount);
    api.get.mockImplementation(async (url) => (url === '/api/network/exposure' ? { level: 'public', share_links: true, tone: 'neutral' } : { state: 'Stopped' }));
    await ra.installRemoteAccess(mount);
    await vi.waitFor(() => expect(mount.querySelector('.remote-exposure-head')?.textContent).toContain('On the internet: share links.'));
    const line = document.getElementById(ex.LINE_ID);
    expect(mount.firstElementChild).toBe(line);
    expect(line.className).toBe('remote-exposure remote-exposure--neutral');
    expect(line.getAttribute('role')).toBe('status');

    api.get.mockRejectedValue(new Error('offline'));
    await ex.renderExposure(line);
    expect(line.hidden).toBe(true);
    expect(ex.installExposure(null)).toBeNull();
  });
});
