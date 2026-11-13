import { describe, it, expect, vi, beforeEach } from 'vitest';

const showToast = vi.fn();
vi.mock('../toast.js', () => ({ showToast, showConfirmToast: vi.fn() }));
const copyText = vi.fn(() => Promise.resolve());
vi.mock('../utils.js', async (orig) => ({ ...(await orig()), copyText }));

const { homeHtml, portRowsHtml, renderHome, renderPortRows, showTailscaleOptions } = await import('../components/management/network-home.js');

describe('SET-24 m: This NAS at home and the port rows', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="home"></div><ul id="rows"></ul>';
  });

  it('the address is a value, never part of the translated sentence, and is escaped', () => {
    const html = homeHtml({ primary_ip: '<b>10.0.0.5</b>' });
    expect(html).toContain('<strong translate="no">&lt;b&gt;10.0.0.5&lt;/b&gt;</strong>');
    expect(html).not.toContain('<b>10');
  });

  it('an address the host marks as not found is said in words', () => {
    expect(homeHtml({ primary_ip: '?' })).toContain('Kiboto could not read this NAS');
  });

  it('says Unknown for what the host did not say', () => {
    const box = /** @type {HTMLElement} */ (document.getElementById('home'));
    box.innerHTML = homeHtml({ primary_ip: '10.0.0.5' });
    expect(box.querySelector('.net-dl')?.textContent?.replace(/\s*\n\s*/g, '')).toBe('RouterUnknownName serversUnknownThroughUnknown');
  });

  it('Copy copies the address and says so; a failed copy says what to do', async () => {
    const box = /** @type {HTMLElement} */ (document.getElementById('home'));
    renderHome(box, { primary_ip: '10.0.0.5' });
    /** @type {HTMLElement} */ (box.querySelector('[data-copy]')).click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Address copied.', 'success'));
    expect(copyText).toHaveBeenCalledWith('10.0.0.5');
    copyText.mockRejectedValueOnce(new Error('no'));
    /** @type {HTMLElement} */ (box.querySelector('[data-copy]')).click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Could not copy. Select the address and copy it yourself.', 'error'));
    renderHome(null, {}); // no box, nothing to do
  });

  it('"Name this port" hands the port to the caller', () => {
    const list = /** @type {HTMLElement} */ (document.getElementById('rows'));
    const onName = vi.fn();
    renderPortRows(list, [{ name: 'eth0', is_up: true, speed_human: '1 Gbps' }], onName);
    /** @type {HTMLElement} */ (list.querySelector('[data-name-port]')).click();
    expect(onName).toHaveBeenCalledWith('eth0');
    expect(list.querySelector('.net-port-speed')?.textContent).toBe('1 Gbps');
    renderPortRows(null, [], onName);
  });

  it('a port named by its owner shows that name with the port beside it', () => {
    expect(portRowsHtml([{ name: 'eth2', alias: 'To the TV', is_up: false }])).toContain('To the TV (eth2)');
    expect(portRowsHtml([])).toContain('No network ports found.');
  });

  it('Tailscale options show while Tailscale is connected, otherwise the way to connect it (SET-24 n)', () => {
    document.body.innerHTML = '<p id="net-ts-off"></p><div id="net-ts-opts" hidden></div>';
    showTailscaleOptions(true);
    expect(document.getElementById('net-ts-opts')?.hidden).toBe(false);
    expect(document.getElementById('net-ts-off')?.hidden).toBe(true);
    showTailscaleOptions(false);
    expect(document.getElementById('net-ts-opts')?.hidden).toBe(true);
    expect(document.getElementById('net-ts-off')?.hidden).toBe(false);
    document.body.innerHTML = '';
    expect(() => showTailscaleOptions(true)).not.toThrow();
  });
});
