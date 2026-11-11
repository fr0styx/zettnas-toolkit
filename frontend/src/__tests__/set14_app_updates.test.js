// SET-14: the update check says "up to date" only when it found out, and "Update all" says what
// was updated and what was not.
import { describe, it, expect, afterEach } from 'vitest';
import { setLanguage } from '../i18n.js';
import { checkSaid, updateAllSaid } from '../components/app-updates-said.js';

describe('the update check', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('does not say "up to date" when nothing was checked', async () => {
    expect(checkSaid({ checked: false, updates_available_count: 0 })).toEqual(['The update check could not run: Docker did not answer.', 'error']);
    expect(checkSaid({ checked: true, updates_available_count: 2 })).toEqual(['2 apps have an update.', 'warn']);
    expect(checkSaid({ checked: true, updates_available_count: 0, unchecked: ['immich', 'plex'] })[0]).toBe(
      'No update found. 2 apps could not be checked, because the place its image comes from did not answer: immich, plex',
    );
    expect(checkSaid({ checked: true, updates_available_count: 0, unchecked: [] })).toEqual(['Every app is up to date.', 'success']);
    expect(checkSaid({ updates_available_count: 0 })).toEqual(['Every app is up to date.', 'success']); // a server from before
    expect(checkSaid(null)[1]).toBe('success');
    await setLanguage('de');
    expect(checkSaid({ checked: true, updates_available_count: 1 })[0]).toBe('Für 1 App gibt es ein Update.');
  });

  it('"Update all" names what failed', () => {
    expect(updateAllSaid({ updated: [{ name: 'plex' }, { name: 'immich' }], failed: [], skipped: [] })).toEqual(['2 apps were updated: plex, immich', 'success']);
    expect(updateAllSaid({ updated: [{ name: 'plex' }], failed: [{ name: 'immich', error: 'pull failed' }] })).toEqual(['1 updated. Not updated: immich: pull failed', 'error']); // "All container updates dispatched."
    expect(updateAllSaid({ updated: [], failed: [], skipped: [{ name: 'kiboto' }] })).toEqual(['Nothing was updated.', 'info']);
    expect(updateAllSaid(undefined)).toEqual(['Nothing was updated.', 'info']);
  });
});
