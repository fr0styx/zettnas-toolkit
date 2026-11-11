// SET-08: the Fans tab sends only the field that changed, says when a change was refused, and
// re-reads what the server holds.
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { post: vi.fn(), get: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { manualChange, modeChange, saveFans } from '../components/fan-save.js';

describe('saving a fan setting', () => {
  beforeEach(() => vi.clearAllMocks());

  it('sends the change as it is and hands the saved settings on', async () => {
    api.post.mockResolvedValue({ profile: 'quiet', zero_rpm_enabled: true });
    const onSaved = vi.fn();
    const reread = vi.fn();
    const data = await saveFans({ zero_rpm_enabled: true }, { onSaved, reread });
    expect(api.post).toHaveBeenCalledWith('/api/fans', { zero_rpm_enabled: true });
    expect(onSaved).toHaveBeenCalledWith({ profile: 'quiet', zero_rpm_enabled: true });
    expect(data.profile).toBe('quiet');
    expect(reread).not.toHaveBeenCalled();
    expect(showToast).not.toHaveBeenCalled();
  });

  it('says when the change was refused and puts the controls back', async () => {
    api.post.mockRejectedValue(Object.assign(new Error('403'), { detail: 'You may not change the fans.' }));
    const onSaved = vi.fn();
    const reread = vi.fn();
    expect(await saveFans({ profile: 'full' }, { onSaved, reread })).toBeNull();
    expect(onSaved).not.toHaveBeenCalled();
    expect(reread).toHaveBeenCalledTimes(1);
    expect(showToast).toHaveBeenCalledWith('The fan setting was not changed: You may not change the fans.', 'error');
  });

  it('works without hooks', async () => {
    api.post.mockRejectedValue(new Error('offline'));
    expect(await saveFans({ cpu_hold_secs: 30 })).toBeNull();
    expect(showToast.mock.calls[0][0]).toContain('offline');
  });

  it('a mode button sends the mode, the slider the mode and its value: never the curve or fixed temperatures', () => {
    expect(modeChange('quiet')).toEqual({ profile: 'quiet' });
    expect(manualChange('45')).toEqual({ profile: 'manual', manual_pct: 45 });
  });
});
