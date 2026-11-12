/** S29: "Delete pool and erase its drives" shows the drives first, asks for the name and the password. */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showDangerConfirm: vi.fn(), showPromptToast: vi.fn() }));
import { showToast, showDangerConfirm, showPromptToast } from '../toast.js';
import { api } from '../api.js';
import { eraseButtonHtml, erasePool } from '../components/chassis-visualizer.js';

describe('erase a pool (S29)', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('offers the button only where the server can confirm the drives', () => {
    expect(eraseButtonHtml({ id: 'tank', erasable: true })).toContain('data-pool-id="tank"');
    expect(eraseButtonHtml({ id: 'cache', erasable: false })).toBe('');
    expect(eraseButtonHtml(null)).toBe('');
  });

  it('lists the drives and shared folders, needs the typed name and the password, then erases', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ drives: ['/dev/sdb1', '/dev/sdc1'], shares: ['photos'] });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ drives: ['/dev/sdb1', '/dev/sdc1'] });
    showDangerConfirm.mockImplementation((title, msg, ok, cancel, opts) => {
      expect(msg).toContain('/dev/sdb1, /dev/sdc1');
      expect(msg).toContain('photos');
      expect(opts.typeToConfirm).toBe('tank');
      ok();
    });
    showPromptToast.mockImplementation((title, msg, def, ok) => ok(' secret '));
    const done = vi.fn();
    expect(await erasePool('tank', done)).toBe(true);
    expect(post).toHaveBeenCalledWith('/api/storage/pools/tank/erase', { confirm_name: 'tank', current_password: 'secret' }, { confirmed: true });
    expect(done).toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('2 drives erased'), 'success');
  });

  it('stops when the plan is refused, on cancel, without a password, or when the erase fails', async () => {
    const get = vi.spyOn(api, 'get').mockRejectedValueOnce(new Error('/dev/sdd1 could not be confirmed'));
    expect(await erasePool('tank')).toBe(false);
    expect(showToast).toHaveBeenLastCalledWith('/dev/sdd1 could not be confirmed', 'error');
    get.mockResolvedValue({ drives: ['/dev/sdb1'] });
    showDangerConfirm.mockImplementation((t, m, ok, cancel) => cancel());
    expect(await erasePool('tank')).toBe(false);
    showDangerConfirm.mockImplementation((t, m, ok) => ok());
    showPromptToast.mockImplementation((t, m, d, ok, cancel) => cancel());
    expect(await erasePool('tank')).toBe(false);
    showPromptToast.mockImplementation((t, m, d, ok) => ok('pw'));
    vi.spyOn(api, 'post').mockRejectedValue(new Error('target is busy'));
    expect(await erasePool('tank')).toBe(false);
    expect(showToast).toHaveBeenLastCalledWith('target is busy', 'error');
  });
});
