import { describe, it, expect, afterEach } from 'vitest';
import { setLanguage } from '../i18n.js';
import { checkDetails, checkName } from '../components/management/security.js';

afterEach(async () => {
  await setLanguage('en');
});

describe('the security check in the reader\'s language (SET-14)', () => {
  it('names and sentences with their values', async () => {
    await setLanguage('de');
    const row = { id: 'stale_api_tokens', name: 'API Token Hygiene', passed: false, details: 'x', params: { count: 2 } };
    expect(checkName(row)).toBe('Ungenutzte App-Schlüssel');
    expect(checkDetails(row)).toBe('2 App-Schlüssel wurden seit mehr als 90 Tagen nicht benutzt');
    const shares = { id: 'smb_guest_access', passed: false, details: 'x', params: { shares: 'Media, Public' } };
    expect(checkDetails(shares)).toBe('Ohne Passwort offen: Media, Public');
  });

  it('a row without params keeps the server\'s sentence; an unknown row keeps its name', async () => {
    await setLanguage('fr');
    expect(checkDetails({ id: 'nfs_open_exports', passed: false, details: '/mnt/user/x: *' })).toBe('/mnt/user/x: *');
    expect(checkName({ id: 'something_new', name: 'Something new' })).toBe('Something new');
  });
});
