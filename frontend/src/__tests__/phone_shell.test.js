import { describe, it, expect, vi } from 'vitest';
import { enablePhoneShell, launcherHtml, tabsHtml, TILES } from '../components/phone-shell.js';

describe('phone mode (UX-13)', () => {
  it('offers the main places as tiles and five bottom tabs', () => {
    document.body.innerHTML = launcherHtml();
    expect(document.querySelectorAll('[data-phone-open]').length).toBe(TILES().length);
    document.body.innerHTML = tabsHtml();
    expect([...document.querySelectorAll('[data-phone-tab]')].map((b) => b.dataset.phoneTab)).toEqual(['home', 'files', 'apps', 'alerts', 'settings']);
  });

  it('opens places through the deep-link routes and hides the launcher behind a page', () => {
    document.body.innerHTML = '';
    window.openFileManager = vi.fn();
    enablePhoneShell(true);
    expect(document.body.classList.contains('phone-shell')).toBe(true);
    document.querySelector('[data-phone-open="files"]').click();
    expect(window.openFileManager).toHaveBeenCalled();
    enablePhoneShell(false);
    expect(document.getElementById('phone-shell')).toBeNull();
  });
});
