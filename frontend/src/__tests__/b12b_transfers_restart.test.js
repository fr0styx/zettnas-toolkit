import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));
vi.mock('../api.js', () => ({ api: { post: vi.fn(), delete: vi.fn() } }));

import { transferCenter, taskStatus } from '../components/transfer-center.js';
import { showToast, showConfirmToast } from '../toast.js';
import { api } from '../api.js';

const stopped = { id: 't1', status: 'interrupted', action: 'copy', sources: ['/mnt/user/a'], destination: '/mnt/user/b', created_at: 1, can_undo: true };

describe('B12b (REL-25): a transfer stopped by a restart', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    transferCenter.tasks.clear();
    transferCenter.watch.clear();
    transferCenter.host = null;
    document.body.innerHTML = '';
    transferCenter.ensureDom();
  });

  const click = (act) => transferCenter.host.querySelector(`[data-act='${act}']`).click();

  it('says so and offers resume, undo and dismiss', () => {
    expect(taskStatus(stopped)).toBe('Stopped by a restart');
    transferCenter.update(stopped);
    transferCenter.render();
    for (const act of ['resume', 'undo', 'dismiss']) expect(transferCenter.host.querySelector(`[data-act='${act}']`)).not.toBeNull();
    transferCenter.update({ ...stopped, can_undo: false });
    transferCenter.render();
    expect(transferCenter.host.querySelector('[data-act="undo"]')).toBeNull();
  });

  it('resume follows the rerun in place of the stopped transfer', async () => {
    api.post.mockResolvedValue({ status: 'ok', task: { id: 't2', status: 'running', action: 'copy', sources: ['/mnt/user/a'], destination: '/mnt/user/b' } });
    transferCenter.update(stopped);
    transferCenter.render();
    click('resume');
    await vi.waitFor(() => expect(transferCenter.tasks.has('t2')).toBe(true));
    expect(api.post).toHaveBeenCalledWith('/api/fs/transfers/t1/resume', {});
    expect(transferCenter.tasks.has('t1')).toBe(false);
  });

  it('undo asks first and says what it kept', async () => {
    api.post.mockResolvedValue({ status: 'ok', binned: 0, kept: ['album'], tasks: [] });
    transferCenter.update(stopped);
    transferCenter.render();
    click('undo');
    expect(api.post).not.toHaveBeenCalled();
    const [, onOk] = showConfirmToast.mock.calls[0];
    await onOk();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.stringContaining('album'), 'info'));
    expect(transferCenter.tasks.has('t1')).toBe(false);
  });

  it('a failed dismiss says why', async () => {
    api.post.mockRejectedValue(new Error('gone'));
    transferCenter.update(stopped);
    transferCenter.render();
    click('dismiss');
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.stringContaining('gone'), 'error'));
  });
});
