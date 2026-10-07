import { describe, it, expect, beforeEach, vi } from 'vitest';
import { handlePendingIngest } from '../components/dashboard.js';
import { showConfirmToast, hideConfirmToast } from '../toast.js';
import { api } from '../api.js';

describe('Media Slot Auto-Ingest Confirmation Dialog', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="confirm-toast-backdrop"></div>
      <div id="confirm-toast-modal"></div>
      <div id="copy-toast" style="opacity:0;"></div>
      <div id="copy-toast-backdrop" style="opacity:0;"></div>
    `;
    vi.restoreAllMocks();
  });

  it('renders confirmation dialog when pending_ingest is present', () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ status: 'started' });

    const pending = {
      slot: 'sd',
      dev: 'sdd1',
      size: 64 * 1e9,
      dest: '/mnt/user/Photos',
      ts: 123456789,
    };

    handlePendingIngest(pending);

    const modal = document.getElementById('confirm-toast-modal');
    const backdrop = document.getElementById('confirm-toast-backdrop');

    expect(modal).not.toBeNull();
    expect(modal.style.display).toBe('block');
    expect(backdrop.style.display).toBe('block');

    const titleEl = document.getElementById('confirm-toast-title');
    expect(titleEl.textContent).toContain('Media Card Ingest');

    const msgEl = document.getElementById('confirm-toast-msg');
    expect(msgEl.textContent).toContain('SD Card');
    expect(msgEl.textContent).toContain('/dev/sdd1');
    expect(msgEl.textContent).toContain('/mnt/user/Photos');

    const okBtn = document.getElementById('confirm-toast-ok');
    expect(okBtn.textContent).toContain('Start Ingest');

    // Click confirm button
    okBtn.click();
    expect(postSpy).toHaveBeenCalledWith('/api/copy/start', {
      source: 'sd',
      dest: '/mnt/user/Photos',
    });
  });

  it('dismisses dialog and calls /api/copy/dismiss-ingest when Cancel is clicked', () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ status: 'dismissed' });

    const pending = {
      slot: 'tf',
      dev: 'sde1',
      size: 32 * 1e9,
      dest: '/mnt/user/DCIM',
      ts: 987654321,
    };

    handlePendingIngest(pending);

    const cancelBtn = document.getElementById('confirm-toast-cancel');
    expect(cancelBtn).not.toBeNull();
    cancelBtn.click();

    expect(postSpy).toHaveBeenCalledWith('/api/copy/dismiss-ingest');
  });

  it('automatically hides confirmation dialog when card is removed (pending_ingest becomes null)', () => {
    const pending = {
      slot: 'sd',
      dev: 'sdd1',
      size: 16 * 1e9,
      dest: '/mnt/user/',
      ts: 55555,
    };

    handlePendingIngest(pending);
    const modal = document.getElementById('confirm-toast-modal');
    expect(modal.style.display).toBe('block');

    // Card removed
    handlePendingIngest(null);
    expect(modal.style.opacity).toBe('0');
  });

  it('does not re-prompt when Eject is clicked and card remains in slot', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok' });

    const pending = {
      slot: 'sd',
      dev: 'sdd1',
      size: 128 * 1e9,
      dest: '/mnt/user/DCIM',
      ts: 77777,
    };

    handlePendingIngest(pending);
    const modal = document.getElementById('confirm-toast-modal');
    expect(modal.style.display).toBe('block');

    const ejectBtn = document.getElementById('confirm-toast-eject');
    expect(ejectBtn).not.toBeNull();
    ejectBtn.click();

    expect(postSpy).toHaveBeenCalledWith('/api/copy/eject', { slot: 'sd' });

    // Simulate subsequent stats ticks arriving while card remains in slot
    handlePendingIngest({ ...pending, ts: 88888 });

    // Modal must NOT be re-displayed (opacity remains 0) because slot is in ejected state
    expect(modal.style.opacity).toBe('0');
  });
});
