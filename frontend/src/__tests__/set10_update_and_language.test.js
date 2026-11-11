// SET-10: a failed update check says so; Revert can be reached; the Language menu in Settings works.
import { describe, it, expect, vi } from 'vitest';
import { checkFailed, checkFailedText, keepRevertReachable } from '../components/management/update-status.js';
import * as i18n from '../i18n.js';

describe('the update status', () => {
  it('a check that got no answer is not "up to date"', () => {
    const failed = { update_available: false, current_version: '2.0.0', error: 'GitHub API HTTP 403' };
    expect(checkFailed(failed)).toBe(true);
    expect(checkFailed({ update_available: false, error: null })).toBe(false);
    expect(checkFailed({ update_available: true, error: 'old' })).toBe(false);
    expect(checkFailed(null)).toBe(false);
    const said = checkFailedText(failed);
    expect(said.title).toBe('Could not check for updates');
    expect(said.desc).toContain('v2.0.0');
    expect(said.desc).toContain('GitHub API HTTP 403');
    expect(checkFailedText({ error: 'x'.repeat(500) }).desc.length).toBeLessThan(260);
  });

  it('Revert leaves the box that is hidden when no update is waiting', () => {
    document.body.innerHTML = '<div id="box" style="display:none"><button id="revert"></button></div>';
    const box = document.getElementById('box');
    const btn = document.getElementById('revert');
    expect(keepRevertReachable(btn, box)).toBe(true);
    expect(box.contains(btn)).toBe(false);
    expect(box.nextElementSibling).toBe(btn);
    expect(keepRevertReachable(btn, box)).toBe(false); // already outside
    expect(keepRevertReachable(null, box)).toBe(false);
  });
});

describe('the Language menu', () => {
  it('a menu drawn after the start changes the language', async () => {
    i18n.bindLanguageMenus();
    const set = vi.spyOn(i18n, 'setLanguage');
    document.body.innerHTML = '<select id="mgmt-lang-select" class="language-picker-select"><option value="en">English</option><option value="de">Deutsch</option></select><select id="other"><option value="x">x</option></select>';
    const menu = document.getElementById('mgmt-lang-select');
    menu.value = 'de';
    menu.dispatchEvent(new Event('change', { bubbles: true }));
    await vi.waitFor(() => expect(i18n.getLanguage()).toBe('de'));
    document.getElementById('other').dispatchEvent(new Event('change', { bubbles: true }));
    expect(i18n.getLanguage()).toBe('de'); // other menus are left alone
    menu.value = 'en';
    menu.dispatchEvent(new Event('change', { bubbles: true }));
    await vi.waitFor(() => expect(i18n.getLanguage()).toBe('en'));
    set.mockRestore();
  });
});
