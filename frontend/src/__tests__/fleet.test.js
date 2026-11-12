import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
const { api } = await import('../api.js');
const toast = await import('../toast.js');
const { fleetHtml, summaryHtml, pickHtml, loadFleetCard } = await import('../components/management/fleet.js');

const tick = () => new Promise((r) => setTimeout(r, 0));
const SUMMARY = {
  name: 'cellar', version: '2.0.0', uptime: 3 * 86400 + 5,
  storage: [{ total: 4e12, free: 1e12 }],
  backups: [{ name: 'Photos', last_backup: 1762790400, last_result: 'ok' }, { name: 'Docs', last_backup: null, last_result: 'failed: disk' }],
};
const PEER = { id: 'b1', name: 'cellar', address: 'http://100.101.102.103:8082', offer_space: false, backup_repo: '', summary: SUMMARY };
const ST = { name: 'attic', address: 'https://attic.x.ts.net', pairing_waiting: false, peers: [PEER] };

describe('your Kiboto boxes (RES-9)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="network-services-grid"></div>';
  });

  it('shows each box at a glance, or why it is not answering', () => {
    expect(fleetHtml({ ...ST, address: '' })).toContain('Needs Tailscale');
    expect(fleetHtml({ ...ST, peers: [] })).toContain('No other Kiboto box');
    const html = summaryHtml(SUMMARY);
    expect(html).toContain('Kiboto 2.0.0');
    expect(html).toContain('up 3 days');
    expect(html).toContain('Photos');
    expect(html).toContain('never');
    expect(html).toContain('failed: disk');
    expect(summaryHtml({ storage: [], backups: [] })).toContain('No off-site backups');
    expect(summaryHtml({ error: 'timed out' })).toContain('Not answering: timed out');
    expect(summaryHtml(undefined)).toBe('');
    expect(fleetHtml(ST)).toContain('Back up to this box');
    expect(fleetHtml({ ...ST, peers: [{ ...PEER, backup_repo: 'buddy-b1', offer_space: true }] })).toContain('backs up there');
    expect(pickHtml('b1', [])).toContain('No shares');
    expect(pickHtml('b1', [{ name: 'photos', path: '/mnt/user/photos' }])).toContain('value="/mnt/user/photos"');
  });

  it('makes a code, pairs, gives space, sets up a backup and unpairs', async () => {
    api.get.mockImplementation(async (url) => (url === '/api/storage/shares' ? { shares: [{ name: 'photos', path: '/mnt/user/photos' }] } : ST));
    await loadFleetCard();
    const card = document.getElementById('fleet-card');

    api.post.mockResolvedValueOnce({ code: 'ABCD-EFGH-JKLM-NPQR', address: 'https://attic.x.ts.net', expires_in: 600 });
    /** @type {HTMLElement} */ (card.querySelector('[data-fleet="code"]')).click();
    await tick();
    expect(card.querySelector('[data-fleet-code]').textContent).toContain('ABCD-EFGH-JKLM-NPQR');

    api.post.mockResolvedValueOnce(ST);
    const add = /** @type {HTMLFormElement} */ (card.querySelector('[data-fleet-add]'));
    /** @type {HTMLInputElement} */ (add.elements.namedItem('address')).value = ' http://100.64.0.2:8082 ';
    /** @type {HTMLInputElement} */ (add.elements.namedItem('code')).value = 'abcd-efgh-jklm-npqr';
    add.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await tick();
    expect(api.post).toHaveBeenLastCalledWith('/api/fleet/peers', { address: 'http://100.64.0.2:8082', code: 'abcd-efgh-jklm-npqr' });

    api.put.mockResolvedValueOnce({ ...ST, peers: [{ ...PEER, offer_space: true }] });
    const offer = /** @type {HTMLInputElement} */ (card.querySelector('[data-fleet-offer="b1"]'));
    offer.checked = true;
    offer.dispatchEvent(new Event('change', { bubbles: true }));
    await tick();
    expect(api.put).toHaveBeenCalledWith('/api/fleet/peers/b1/offer', { enabled: true });

    /** @type {HTMLElement} */ (card.querySelector('[data-fleet-backup="b1"]')).click();
    await tick();
    await tick();
    const pick = /** @type {HTMLFormElement} */ (card.querySelector('[data-fleet-paths="b1"]'));
    /** @type {HTMLInputElement} */ (pick.querySelector('input[name="paths"]')).checked = true;
    api.post.mockResolvedValueOnce({ ...ST, peers: [{ ...PEER, backup_repo: 'buddy-b1' }] });
    pick.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await tick();
    expect(api.post).toHaveBeenLastCalledWith('/api/fleet/peers/b1/backup', { paths: ['/mnt/user/photos'] });
    expect(toast.showToast).toHaveBeenCalledWith(expect.stringContaining('Set up'), 'success');

    api.delete.mockResolvedValueOnce({ ...ST, peers: [] });
    /** @type {HTMLElement} */ (card.querySelector('[data-fleet-forget="b1"]')).click();
    await tick();
    expect(api.delete).toHaveBeenCalledWith('/api/fleet/peers/b1');
    expect(card.textContent).toContain('No other Kiboto box');
  });

  it('puts a refused switch back and reports errors', async () => {
    api.get.mockResolvedValue(ST);
    await loadFleetCard();
    const card = document.getElementById('fleet-card');
    api.put.mockRejectedValueOnce(Object.assign(new Error('confirm'), { status: 428 }));
    const offer = /** @type {HTMLInputElement} */ (card.querySelector('[data-fleet-offer="b1"]'));
    offer.checked = true;
    offer.dispatchEvent(new Event('change', { bubbles: true }));
    await tick();
    await tick();
    expect(offer.checked).toBe(false);
    expect(toast.showToast).not.toHaveBeenCalled();
    api.post.mockRejectedValueOnce(new Error('Connect Tailscale first'));
    /** @type {HTMLElement} */ (card.querySelector('[data-fleet="code"]')).click();
    await tick();
    expect(toast.showToast).toHaveBeenCalledWith('Connect Tailscale first', 'error');
    api.get.mockRejectedValue(new Error('offline'));
    await loadFleetCard();
    expect(document.getElementById('fleet-body').textContent).toBe('offline');
  });

  it('builds into its new place when that is there (SET-24)', async () => {
    document.body.innerHTML = '<div id="backup-fleet-grid"></div><div id="network-services-grid"></div>';
    await loadFleetCard();
    expect(document.getElementById('fleet-card').parentElement.id).toBe('backup-fleet-grid');
  });
});
