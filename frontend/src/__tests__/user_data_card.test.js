import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');
const { installMyData, installUserDataFor, userDataHtml } = await import('../components/management/user-data.js');

const flush = () => new Promise((r) => setTimeout(r, 0));
const LEA = { id: 'u-lea', username: 'lea', display_name: 'Lea' };

describe('Your data', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="sec-ldap-card"></div><div id="modal-edit-user"><form></form></div>';
    vi.clearAllMocks();
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:x');
    globalThis.URL.revokeObjectURL = vi.fn();
  });

  it('shows your own card in Security and downloads your data', async () => {
    api.get.mockImplementation(async (url) => (url === '/api/auth/me' ? { id: 'u-me', username: 'me' } : { format: 1 }));
    await installMyData(document);
    const card = document.getElementById('user-data-card');
    expect(card.textContent).toContain('Download what ZettNAS keeps about you');
    card.querySelector('[data-udata="export"]').click();
    await flush();
    expect(api.get).toHaveBeenCalledWith('/api/users/u-me/export');
    expect(URL.createObjectURL).toHaveBeenCalled();
  });

  it('lets an administrator erase a kid\'s chats, log and search data', async () => {
    api.post.mockResolvedValue({ status: 'ok' });
    installUserDataFor(document.getElementById('modal-edit-user'), LEA);
    const card = document.getElementById('user-data-card-edit');
    expect(card.textContent).toContain('Lea');
    card.querySelector('[data-udata="erase"]').click();
    await flush();
    expect(api.post).toHaveBeenCalledWith('/api/users/u-lea/erase-data', { parts: ['chats', 'ai_log', 'index'] });
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('erased'), 'success');
  });

  it('says nothing when the confirmation was cancelled', async () => {
    api.post.mockRejectedValue(Object.assign(new Error('Cancelled'), { error: 'cancelled' }));
    installUserDataFor(document.getElementById('modal-edit-user'), LEA);
    document.querySelector('[data-udata="erase"]').click();
    await flush();
    expect(showToast).not.toHaveBeenCalled();
  });

  it('reports a failed download and escapes names', async () => {
    api.get.mockRejectedValue(new Error('offline'));
    installUserDataFor(document.getElementById('modal-edit-user'), LEA);
    document.querySelector('[data-udata="export"]').click();
    await flush();
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('offline'), 'error');
    expect(String(userDataHtml({ username: '<i>x</i>' }, false))).not.toContain('<i>x</i>');
  });

  it('stays away when nobody is signed in', async () => {
    api.get.mockRejectedValue(new Error('401'));
    await installMyData(document);
    expect(document.getElementById('user-data-card')).toBeNull();
  });
});
