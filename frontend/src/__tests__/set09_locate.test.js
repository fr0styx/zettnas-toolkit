// SET-09: "Find this drive" speaks after the server's answer and names the light that moves.
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('../toast.js', async (orig) => ({ ...(await orig()), showToast: vi.fn() }));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { locateSaid } from '../components/locate-text.js';
import * as chassis from '../components/chassis-visualizer.js';

describe('what "Find this drive" says', () => {
  it('names the light for each method', () => {
    expect(locateSaid({ success: true, method: 'bay_light', duration: 5 }, 'sda')).toEqual({
      text: 'The light of the bay that holds sda blinks for 5 seconds.',
      tone: 'success',
      blinking: true,
    });
    expect(locateSaid({ success: true, method: 'activity_light', duration: 8 }, 'sdb').text).toBe('The activity light of sdb flickers for 8 seconds. Look for the light that moves.');
  });

  it('says when no light could be blinked, with the reason when there is one', () => {
    expect(locateSaid({ success: false, error: 'The drive could not be read: No such device' }, 'sdc')).toEqual({
      text: 'No light could be blinked for sdc: The drive could not be read: No such device',
      tone: 'error',
      blinking: false,
    });
    expect(locateSaid({ success: false }, 'sdc').text).toBe('No light could be blinked for sdc.');
    expect(locateSaid(null, 'sdc').tone).toBe('error');
  });
});

describe('the button', () => {
  beforeEach(() => vi.clearAllMocks());

  it('says nothing before the answer, then names the light and marks the tile', async () => {
    let answer;
    vi.spyOn(api, 'post').mockReturnValue(new Promise((resolve) => { answer = resolve; }));
    const tile = document.createElement('div');
    const done = chassis.triggerLocateDisk('sda', tile);
    await Promise.resolve();
    expect(showToast).not.toHaveBeenCalled();
    expect(tile.classList.contains('strobe-active')).toBe(false);
    answer({ success: true, method: 'activity_light', duration: 5 });
    await done;
    expect(api.post).toHaveBeenCalledWith('/api/disk/locate', { dev: 'sda', duration: 5 });
    expect(showToast).toHaveBeenCalledWith('The activity light of sda flickers for 5 seconds. Look for the light that moves.', 'success');
    expect(tile.classList.contains('strobe-active')).toBe(true);
  });

  it('says so when the server refused or failed, and marks nothing', async () => {
    vi.spyOn(api, 'post').mockRejectedValue(Object.assign(new Error('403'), { detail: 'You may not do this.' }));
    const tile = document.createElement('div');
    await chassis.triggerLocateDisk('sda', tile);
    expect(showToast).toHaveBeenCalledWith('No light could be blinked for sda: You may not do this.', 'error');
    expect(tile.classList.contains('strobe-active')).toBe(false);
  });

  it('plays no sound: the page has no beep left', () => {
    expect(chassis.playChirp).toBeUndefined();
  });
});
