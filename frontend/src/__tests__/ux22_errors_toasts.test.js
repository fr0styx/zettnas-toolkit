import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { explain, detailsFor } from '../error-text.js';
import { setLanguage } from '../i18n.js';
import { showToast, showActionToast, TOAST_MS } from '../toast.js';
import { announceChange } from '../a11y.js';

describe('UX-22: errors in the person\'s language', () => {
  afterEach(async () => { await setLanguage('en'); });

  it('keeps the server sentence in English', () => {
    expect(explain('A share named Photos already exists.', 'conflict')).toContain('A share named Photos already exists.');
  });

  it('translates by code elsewhere and keeps the server words as details', async () => {
    await setLanguage('de');
    const msg = explain('A share named Photos already exists.', 'conflict');
    expect(msg).toContain('Das kollidiert mit etwas');
    expect(msg).not.toContain('Photos');
    expect(detailsFor(msg)).toBe('A share named Photos already exists.');
    expect(explain('boom', 'some_new_code', { code: 500 })).toBe('Auf dem Server ist ein Fehler aufgetreten.');
  });
});

describe('UX-27: humane toasts', () => {
  beforeEach(() => { document.body.innerHTML = ''; vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it('keeps an error until it is closed and shows its details', async () => {
    await setLanguage('de');
    const msg = explain('Disk sdb is busy.', 'conflict');
    showToast(msg, 'error');
    vi.advanceTimersByTime(TOAST_MS * 3);
    const item = document.querySelector('.top-toast-item');
    expect(item).not.toBeNull();
    expect(item.querySelector('.top-toast-details-text').textContent).toBe('Disk sdb is busy.');
    await setLanguage('en');
  });

  it('waits while the pointer is on a message', () => {
    showToast('Saved.', 'success');
    const item = document.querySelector('.top-toast-item');
    item.dispatchEvent(new Event('mouseenter'));
    vi.advanceTimersByTime(TOAST_MS * 2);
    expect(item._dismissTimer).toBeFalsy();
    item.dispatchEvent(new Event('mouseleave'));
    vi.advanceTimersByTime(TOAST_MS + 500);
    expect(item.classList.contains('show')).toBe(false);
  });

  it('takes the newest Undo offer with Ctrl+Z, not other actions', () => {
    const undo = vi.fn();
    const other = vi.fn();
    showActionToast('Moved 2 items to the Recycle Bin', 'Undo', undo);
    showActionToast('Ready', 'Open', other);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true }));
    expect(undo).toHaveBeenCalledTimes(1);
    expect(other).not.toHaveBeenCalled();
  });
});

describe('UX-28: live regions say only changes', () => {
  it('announces when the summary changes, not on first sight or repeats', () => {
    document.body.innerHTML = '';
    vi.useFakeTimers();
    const said = () => document.getElementById('a11y-live-announcer')?.textContent || '';
    announceChange('t-jobs', '1 job running');
    vi.advanceTimersByTime(50);
    expect(said()).toBe('');
    announceChange('t-jobs', '1 job running');
    vi.advanceTimersByTime(50);
    expect(said()).toBe('');
    announceChange('t-jobs', 'No jobs running.');
    vi.advanceTimersByTime(50);
    expect(said()).toBe('No jobs running.');
    vi.useRealTimers();
  });
});
