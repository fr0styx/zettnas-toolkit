/** NFEAT-2: the "Share links from anywhere" card. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { loadPublicLinksCard, publicLinksStatus } = await import('../components/management/public-links.js');

const BASE = { enabled: false, live: false, tailscale: true, base_url: 'https://nas.tail1.ts.net:8443', approval_url: '', error: '' };
const q = (s) => document.querySelector(s);

describe('share links from anywhere (NFEAT-2)', () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="pl-card"><div id="pl-status"></div>
      <button id="pl-toggle" aria-pressed="false"></button><a id="pl-approve" hidden></a></div>`;
  });
  afterEach(() => vi.restoreAllMocks());

  it('says how it stands', () => {
    expect(publicLinksStatus(BASE)).toBe('Off: share links work at home and on your tailnet.');
    expect(publicLinksStatus({ ...BASE, enabled: true, live: true })).toBe('On: share links work from anywhere, at https://nas.tail1.ts.net:8443.');
    expect(publicLinksStatus({ ...BASE, enabled: true })).toBe('Starting…');
    expect(publicLinksStatus({ ...BASE, tailscale: false })).toMatch(/^Needs Tailscale/);
    expect(publicLinksStatus({ ...BASE, approval_url: 'https://login.tailscale.com/f/funnel?x' })).toMatch(/allow Funnel first/);
    expect(publicLinksStatus({ ...BASE, error: 'denied' })).toBe('denied');
  });

  it('turns on, shows an approval link, and off', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(BASE);
    const put = vi.spyOn(api, 'put').mockResolvedValue({ ...BASE, enabled: false, approval_url: 'https://login.tailscale.com/f/funnel?x' });
    await loadPublicLinksCard();
    expect(q('#pl-toggle').disabled).toBe(false);
    q('#pl-toggle').click();
    await vi.waitFor(() => expect(q('#pl-approve').hidden).toBe(false));
    expect(put).toHaveBeenCalledWith('/api/network/public-links', { enabled: true });
    expect(q('#pl-approve').getAttribute('href')).toBe('https://login.tailscale.com/f/funnel?x');
    put.mockResolvedValue({ ...BASE, enabled: true, live: true });
    q('#pl-toggle').click();
    await vi.waitFor(() => expect(q('#pl-toggle').getAttribute('aria-pressed')).toBe('true'));
    put.mockResolvedValue(BASE);
    q('#pl-toggle').click();
    await vi.waitFor(() => expect(put).toHaveBeenLastCalledWith('/api/network/public-links', { enabled: false }));
  });

  it('no Tailscale: the switch waits; a refusal says why; a cancelled yes says nothing', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ ...BASE, tailscale: false });
    await loadPublicLinksCard();
    expect(q('#pl-toggle').disabled).toBe(true);
    const put = vi.spyOn(api, 'put').mockRejectedValue(Object.assign(new Error('Cancelled'), { status: 428 }));
    q('#pl-toggle').disabled = false;
    q('#pl-toggle').click();
    await vi.waitFor(() => expect(put).toHaveBeenCalled());
    expect(showToast).not.toHaveBeenCalled();
    put.mockRejectedValue(new Error('denied'));
    q('#pl-toggle').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('denied', 'error'));
    vi.spyOn(api, 'get').mockRejectedValue(new Error('Forbidden'));
    await loadPublicLinksCard();
    expect(q('#pl-status').textContent).toBe('Forbidden');
    document.body.innerHTML = '';
    await loadPublicLinksCard();
  });
});
