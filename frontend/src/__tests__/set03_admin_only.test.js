import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { isAdministrator, hideAdminOnly } from '../admin-only.js';

const html = readFileSync(resolve(__dirname, '..', 'windows/management-window.html'), 'utf8');
const owner = { scopes: ['*'] };
const family = { scopes: ['shares:read', 'shares:user_write', 'system:view'] };

describe('an administrator’s set-up is not drawn for anyone else (SET-03)', () => {
  it('knows an administrator by the right to change settings', () => {
    expect(isAdministrator(owner)).toBe(true);
    expect(isAdministrator({ scopes: ['system:config'] })).toBe(true);
    expect(isAdministrator(family)).toBe(false);
    expect(isAdministrator({ scopes: [] })).toBe(false);
  });

  it('hides the marked cards for a family member and leaves the personal ones', () => {
    document.body.innerHTML = `
      <div id="pane">
        <div id="advisor" data-admin-only></div><div id="alerts" data-admin-only></div>
        <div id="my-data"></div><div id="push"></div>
      </div>`;
    const pane = document.getElementById('pane');
    expect(hideAdminOnly(pane, owner)).toBe(false);
    expect(document.getElementById('advisor').hidden).toBe(false);
    expect(hideAdminOnly(pane, family)).toBe(true);
    expect(document.getElementById('advisor').hidden).toBe(true);
    expect(document.getElementById('alerts').hidden).toBe(true);
    expect(document.getElementById('my-data').hidden).toBe(false);
    expect(document.getElementById('push').hidden).toBe(false);
  });

  it('marks the administrator cards of the Security and Notifications tabs', () => {
    for (const id of ['sec-advisor-card', 'sec-guard-card', 'sec-sso-card', 'sec-ldap-card', 'file-activity-mount']) {
      const tag = html.match(new RegExp(`<div id="${id}"[^>]*>`));
      expect(tag && tag[0], id).toContain('data-admin-only');
    }
    for (const cls of ['sec-box-3', 'sec-box-4', 'mgmt-card-intro nt-head', 'nt-topbar', 'nt-grid-fill', 'nt-box', 'digest-card']) {
      const tag = html.match(new RegExp(`<(div|section) class="${cls}"[^>]*>`));
      expect(tag && tag[0], cls).toContain('data-admin-only');
    }
    // a person's own things are not marked
    expect(html.match(/<div id="push-device-card"[^>]*>/)[0]).not.toContain('data-admin-only');
    expect(html.match(/<section class="my-alerts-card" aria-labelledby="my-alerts-title"[^>]*>/)[0]).not.toContain('data-admin-only');
  });
});
