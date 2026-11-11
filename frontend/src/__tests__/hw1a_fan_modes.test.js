import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showActionToast: vi.fn() }));
vi.mock('../api.js', () => ({ api: { get: vi.fn(() => Promise.resolve({})), post: vi.fn(() => Promise.resolve({})) } }));
import { showConfirmToast, showToast } from '../toast.js';
import { api } from '../api.js';
import { FIXED_PCT, askFixedSpeed, modeName } from '../components/fan-modes.js';
import { syncFanModeFromStream } from '../components/fan-control.js';
import { chooseHostMode } from '../components/management.js';

describe('the fan modes say what they do (SET-15, Hardware 1)', () => {
  beforeEach(() => {
    showConfirmToast.mockClear();
    showToast.mockClear();
  });

  it('names every mode with the speed the fans really get', () => {
    expect(FIXED_PCT).toEqual({ quiet: 37, balanced: 66, performance: 85, full: 100 });
    expect(modeName('auto')).toBe('Automatic');
    expect(modeName('QUIET')).toBe('Quiet · fixed 37 %');
    expect(modeName('balanced')).toBe('Balanced · fixed 66 %');
    expect(modeName('performance')).toBe('Performance · fixed 85 %');
    expect(modeName('full')).toBe('Full speed');
    expect(modeName('manual', 52.4)).toBe('Fixed 52 %');
    expect(modeName('manual')).toBe('Set by hand');
  });

  it('asks before a fixed speed and does nothing on a no', () => {
    const yes = vi.fn();
    const no = vi.fn();
    askFixedSpeed(37, yes, no);
    const [title, msg, onYes, onNo, opts] = showConfirmToast.mock.calls[0];
    expect(title).toBe('Keep the fans at a fixed 37 %?');
    expect(msg).toMatch(/do not follow the temperature/);
    expect(opts.okText).toBe('Use 37 %');
    expect(yes).not.toHaveBeenCalled();
    onYes();
    expect(yes).toHaveBeenCalledOnce();
    expect(onNo).toBe(no);
  });

  it('the Fans tab follows the live mode, except right after a change made there', () => {
    document.body.innerHTML = '<button class="fan-profile-btn active" data-fan-profile="auto"></button><button class="fan-profile-btn" data-fan-profile="quiet"></button>';
    expect(syncFanModeFromStream({ profile: 'quiet' })).toBe(true);
    expect(document.querySelector('[data-fan-profile="quiet"]').classList.contains('active')).toBe(true);
    expect(document.querySelector('[data-fan-profile="auto"]').classList.contains('active')).toBe(false);
    expect(syncFanModeFromStream({ profile: 'quiet' })).toBe(false); // already shown
    expect(syncFanModeFromStream({})).toBe(false);
    expect(syncFanModeFromStream(null)).toBe(false);
  });

  it('the Host tab puts back the real mode when a change is refused', async () => {
    document.body.innerHTML = '<span id="unraid-profile-current-pill"></span><button class="profile-btn" data-profile="auto"></button><button class="profile-btn" data-profile="quiet"></button>';
    const btns = [...document.querySelectorAll('.profile-btn')];
    await chooseHostMode('quiet', btns[1], btns);
    expect(api.post).toHaveBeenCalledWith('/api/system/profile', { profile: 'quiet' });
    expect(document.getElementById('unraid-profile-current-pill').textContent).toBe('Now: Quiet · fixed 37 %');
    expect(showToast.mock.calls.at(-1)).toEqual(['Cooling: Quiet · fixed 37 %.', 'success']);
    api.post.mockImplementationOnce(() => Promise.reject(new Error('Forbidden')));
    await chooseHostMode('auto', btns[0], btns);
    expect(showToast.mock.calls.at(-1)).toEqual(['The cooling mode was not changed: Forbidden', 'error']);
  });
});
