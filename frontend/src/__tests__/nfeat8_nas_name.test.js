/** NFEAT-8: the "Find this NAS by name" card. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { loadNasNameCard, nasNameStatus } = await import('../components/management/nas-name.js');

const ON = { enabled: true, running: true, name: 'zettnas', address: 'zettnas.local', url: 'http://zettnas.local:8082', also_answers: [], error: '' };
const q = (s) => document.querySelector(s);

describe('find this NAS by name (NFEAT-8)', () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="nas-name-card">
      <div id="nas-name-status"></div><button id="nas-name-toggle" aria-pressed="false"></button>
      <input id="nas-name-input" /><button id="nas-name-save"></button>
      <a id="nas-name-link" hidden></a><div id="nas-name-old" hidden></div></div>`;
  });
  afterEach(() => vi.restoreAllMocks());

  it('says how it stands', () => {
    expect(nasNameStatus(ON)).toBe('On: zettnas.local on this network.');
    expect(nasNameStatus({ ...ON, enabled: false })).toBe('Off: computers find the NAS only by its address.');
    expect(nasNameStatus({ ...ON, running: false })).toBe('Starting…');
    expect(nasNameStatus({ ...ON, error: 'Docker is not reachable' })).toBe('Docker is not reachable');
  });

  it('shows the name and link, renames and turns it off', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(ON);
    const put = vi.spyOn(api, 'put').mockResolvedValue({ ...ON, name: 'smith-nas', address: 'smith-nas.local', url: 'http://smith-nas.local:8082', also_answers: ['zettnas'] });
    await loadNasNameCard();
    expect(q('#nas-name-toggle').getAttribute('aria-pressed')).toBe('true');
    expect(q('#nas-name-input').value).toBe('zettnas');
    expect(q('#nas-name-link').hidden).toBe(false);
    expect(q('#nas-name-link').getAttribute('href')).toBe('http://zettnas.local:8082');
    q('#nas-name-input').value = ' smith-nas ';
    q('#nas-name-input').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await vi.waitFor(() => expect(q('#nas-name-old').hidden).toBe(false));
    expect(put).toHaveBeenCalledWith('/api/network/nas-name', { name: 'smith-nas' });
    expect(q('#nas-name-old').textContent).toBe('Also still answers to zettnas.local, so older bookmarks keep working.');
    put.mockResolvedValue({ ...ON, enabled: false, running: false });
    q('#nas-name-toggle').click();
    await vi.waitFor(() => expect(q('#nas-name-toggle').getAttribute('aria-pressed')).toBe('false'));
    expect(put).toHaveBeenLastCalledWith('/api/network/nas-name', { enabled: false });
    expect(q('#nas-name-link').hidden).toBe(true);
  });

  it('says why a change failed, and a failed load', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(ON);
    vi.spyOn(api, 'put').mockRejectedValue(new Error('Use letters, digits and dashes'));
    await loadNasNameCard();
    q('#nas-name-save').click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Use letters, digits and dashes', 'error'));
    vi.spyOn(api, 'get').mockRejectedValue(new Error('Forbidden'));
    await loadNasNameCard();
    expect(q('#nas-name-status').textContent).toBe('Forbidden');
    document.body.innerHTML = '';
    await loadNasNameCard(); // no card on the page: nothing happens
  });
});
