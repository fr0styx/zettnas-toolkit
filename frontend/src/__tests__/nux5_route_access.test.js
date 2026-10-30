import { describe, it, expect, vi } from 'vitest';

vi.mock('../i18n.js', () => ({ getLanguage: () => 'en', t: (k, f, p = {}) => String(f).replace(/\{(\w+)\}/g, (m, x) => (x in p ? p[x] : m)) }));

const { canOpen, canRun, hasScope, hideUnusable } = await import('../route-access.js');
const { itemText } = await import('../components/management/overview.js');

const KID = { scopes: ['shares:read', 'shares:user_write'] };
const FAMILY = { scopes: ['shares:read', 'shares:user_write', 'system:view', 'ai:knowledge:read'] };
const ADMIN = { scopes: ['*'] };

describe('places by role (NUX-5)', () => {
  it('follows the server rule for scopes', () => {
    expect(hasScope(['*'], 'users:read')).toBe(true);
    expect(hasScope(['storage:*'], 'storage:read')).toBe(true);
    expect(hasScope(['*:read'], 'logs:read')).toBe(true);
    expect(hasScope(['*:read'], 'system:config')).toBe(false);
    expect(hasScope(null, 'x:read')).toBe(false);
  });

  it('a kid gets Files, not the admin places; an admin gets all', () => {
    for (const r of ['users', 'storage', 'backup', 'network', 'ai', 'apps']) expect(canOpen(r, KID)).toBe(false);
    expect(canOpen('files', KID)).toBe(true);
    expect(canOpen('settings', FAMILY)).toBe(true);
    expect(canOpen('users', ADMIN)).toBe(true);
    expect(canOpen('users', null)).toBe(true); // until the account is known
  });

  it('hides tiles and tabs, and brings back only what it hid', () => {
    const root = document.createElement('div');
    root.innerHTML = '<button data-phone-open="users"></button><button data-phone-open="files"></button><button data-phone-open="vms" hidden></button><button data-phone-tab="apps"></button>';
    hideUnusable(root, KID);
    const [users, files, vms, apps] = root.children;
    expect([users.hidden, files.hidden, vms.hidden, apps.hidden]).toEqual([true, false, true, true]);
    hideUnusable(root, ADMIN);
    expect([users.hidden, files.hidden, apps.hidden]).toEqual([false, false, false]);
    expect(vms.hidden).toBe(true); // hidden for another reason (advanced places): left alone
  });

  it("hides Mission Control's sidebar entries too", () => {
    const root = document.createElement('div');
    root.innerHTML = '<button data-route="users"></button><button data-route="hardware"></button><button data-mgmt-target="files"></button>';
    hideUnusable(root, FAMILY);
    expect([...root.children].map((b) => b.hidden)).toEqual([true, true, false]);
  });

  it('Spotlight offers only the commands an account may run', () => {
    expect(canRun('act-spindown', FAMILY)).toBe(false);
    expect(canRun('act-trash-empty', KID)).toBe(false);
    expect(canRun('act-trash-empty', ADMIN)).toBe(true);
    expect(canRun('app-fm', KID)).toBe(true); // Files is for everyone
    expect(canRun('act-spindown', null)).toBe(true); // until the account is known
  });

  it('an item someone cannot fix says who can', () => {
    expect(itemText({ kind: 'storage_full', subject: '91%', tell_admin: true })).toBe('Storage is 91% full. Tell the person who manages ZettNAS.');
  });
});
