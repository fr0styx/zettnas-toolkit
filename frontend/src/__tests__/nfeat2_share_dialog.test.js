/** NFEAT-2: the share dialog makes send-me-files links for folders and shows the public address. */
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
const { api } = await import('../api.js');
const { openShareLinkModal } = await import('../components/file-manager.js');

const q = (s) => document.querySelector(s);

describe('share dialog (NFEAT-2)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
    delete window.getActiveFmInstance;
  });

  it('a folder can receive files instead, and the link works from anywhere', async () => {
    window.getActiveFmInstance = () => ({ fileList: [{ path: '/mnt/user/Inbox', is_dir: true }] });
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      token: 't1', url: '/api/fs/shared/t1', kind: 'upload', expires_at: 1, has_password: false,
      public_url: 'https://nas.tail1.ts.net:8443/api/fs/shared/t1',
    });
    openShareLinkModal('/mnt/user/Inbox', 'Inbox');
    expect(q('#fm-share-upload-row').hidden).toBe(false);
    q('#fm-share-upload').checked = true;
    q('#fm-share-max-dl').value = '3';
    q('#fm-share-submit').click();
    await vi.waitFor(() => expect(q('#fm-share-url-output').value).toBe('https://nas.tail1.ts.net:8443/api/fs/shared/t1'));
    expect(post).toHaveBeenCalledWith('/api/fs/share-links', expect.objectContaining({ kind: 'upload', max_downloads: null }));
    const meta = q('#fm-share-meta-info').textContent;
    expect(meta).toContain('People can send files here but not see what is in the folder');
    expect(meta).toContain('Works from anywhere');
  });

  it('a file is shared for download, at home when public links are off', async () => {
    window.getActiveFmInstance = () => ({ fileList: [{ path: '/mnt/user/a.pdf', is_dir: false }] });
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      token: 't2', url: '/api/fs/shared/t2', expires_at: null, has_password: true, max_downloads: 2, public_url: '',
    });
    openShareLinkModal('/mnt/user/a.pdf', 'a.pdf');
    expect(q('#fm-share-upload-row').hidden).toBe(true);
    q('#fm-share-max-dl').value = '2';
    q('#fm-share-submit').click();
    await vi.waitFor(() => expect(q('#fm-share-url-output').value).toBe(`${window.location.origin}/api/fs/shared/t2`));
    expect(post).toHaveBeenCalledWith('/api/fs/share-links', expect.objectContaining({ kind: 'download', max_downloads: 2 }));
    const meta = q('#fm-share-meta-info').textContent;
    expect(meta).toContain('Never expires');
    expect(meta).toContain('Password protected');
    expect(meta).toContain('At most 2 downloads');
    expect(meta).toContain('Works at home and on your tailnet');
  });
});
