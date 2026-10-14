import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { showBottomSheet } from '../toast.js';

describe('showBottomSheet - Mobile Bottom Sheet Component', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders bottom sheet DOM elements with title, subtitle, and action items', () => {
    const item1Click = vi.fn();
    const item2Click = vi.fn();

    showBottomSheet({
      title: 'Plex Media Server',
      subtitle: 'Image: linuxserver/plex:latest',
      items: [
        { icon: '🔍', label: 'Inspect Container', onClick: item1Click },
        { icon: '🗑️', label: 'Delete Container', destructive: true, onClick: item2Click }
      ]
    });

    const backdrop = document.getElementById('mobile-sheet-backdrop');
    const sheet = document.getElementById('mobile-bottom-sheet');
    expect(backdrop).not.toBeNull();
    expect(sheet).not.toBeNull();

    expect(sheet.textContent).toContain('Plex Media Server');
    expect(sheet.textContent).toContain('Image: linuxserver/plex:latest');

    const items = sheet.querySelectorAll('.sheet-action-item');
    expect(items.length).toBe(2);
    expect(items[0].textContent).toContain('Inspect Container');
    expect(items[0].classList.contains('destructive')).toBe(false);
    expect(items[1].textContent).toContain('Delete Container');
    expect(items[1].classList.contains('destructive')).toBe(true);

    const cancelBtn = sheet.querySelector('.sheet-cancel-btn');
    expect(cancelBtn).not.toBeNull();
  });

  it('clicking an action item triggers onClick callback and closes the sheet', () => {
    const itemClick = vi.fn();

    showBottomSheet({
      title: 'Test Container',
      items: [
        { icon: '🔄', label: 'Restart', onClick: itemClick }
      ]
    });

    const sheet = document.getElementById('mobile-bottom-sheet');
    const itemBtn = sheet.querySelector('.sheet-action-item');
    itemBtn.click();

    expect(itemClick).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(300);
    const backdrop = document.getElementById('mobile-sheet-backdrop');
    expect(backdrop.style.display).toBe('none');
    expect(sheet.style.display).toBe('none');
  });

  it('clicking cancel button triggers onCancel callback and hides sheet', () => {
    const onCancel = vi.fn();

    showBottomSheet({
      title: 'Test Container',
      items: [{ icon: '🔍', label: 'Inspect' }],
      onCancel
    });

    const cancelBtn = document.getElementById('sheet-cancel-btn');
    cancelBtn.click();

    expect(onCancel).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(300);
    const backdrop = document.getElementById('mobile-sheet-backdrop');
    const sheet = document.getElementById('mobile-bottom-sheet');
    expect(backdrop.style.display).toBe('none');
    expect(sheet.style.display).toBe('none');
  });

  it('clicking the backdrop triggers onCancel and dismisses the sheet', () => {
    const onCancel = vi.fn();

    showBottomSheet({
      title: 'Test Container',
      items: [{ icon: '🔍', label: 'Inspect' }],
      onCancel
    });

    const backdrop = document.getElementById('mobile-sheet-backdrop');
    backdrop.click();

    expect(onCancel).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(300);
    expect(backdrop.style.display).toBe('none');
  });

  it('pressing Escape key triggers onCancel and dismisses the sheet', () => {
    const onCancel = vi.fn();

    showBottomSheet({
      title: 'Test Container',
      items: [{ icon: '🔍', label: 'Inspect' }],
      onCancel
    });

    const escEvent = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
    document.dispatchEvent(escEvent);

    expect(onCancel).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(300);
    const backdrop = document.getElementById('mobile-sheet-backdrop');
    expect(backdrop.style.display).toBe('none');
  });

  it('swiping down > 70px on the handle bar dismisses the sheet and calls onCancel', () => {
    const onCancel = vi.fn();

    showBottomSheet({
      title: 'Swipe Test',
      items: [{ icon: '🔍', label: 'Inspect' }],
      onCancel
    });

    const sheet = document.getElementById('mobile-bottom-sheet');
    const handleBar = sheet.querySelector('.sheet-handle-bar');
    expect(handleBar).not.toBeNull();

    handleBar.dispatchEvent(new MouseEvent('pointerdown', { clientY: 100, bubbles: true }));
    handleBar.dispatchEvent(new MouseEvent('pointermove', { clientY: 190, bubbles: true }));
    expect(sheet.style.transform).toContain('translateY(90px)');

    handleBar.dispatchEvent(new MouseEvent('pointerup', { clientY: 190, bubbles: true }));
    expect(onCancel).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(300);
    expect(sheet.style.display).toBe('none');
  });

  it('swiping down < 70px snaps the sheet back without dismissing', () => {
    const onCancel = vi.fn();

    showBottomSheet({
      title: 'Short Swipe Test',
      items: [{ icon: '🔍', label: 'Inspect' }],
      onCancel
    });

    const sheet = document.getElementById('mobile-bottom-sheet');
    const handleBar = sheet.querySelector('.sheet-handle-bar');

    handleBar.dispatchEvent(new MouseEvent('pointerdown', { clientY: 100, bubbles: true }));
    handleBar.dispatchEvent(new MouseEvent('pointermove', { clientY: 140, bubbles: true }));
    handleBar.dispatchEvent(new MouseEvent('pointerup', { clientY: 140, bubbles: true }));

    expect(onCancel).not.toHaveBeenCalled();
    expect(sheet.style.display).toBe('flex');
    expect(sheet.style.transform).toBe('');
  });
});

