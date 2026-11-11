import { describe, it, expect, afterEach } from 'vitest';
import { setLanguage } from '../i18n.js';
import { upsState, upsSentence } from '../components/management/ups.js';

afterEach(async () => {
  await setLanguage('en');
});

describe('the Power page in one sentence (SET-15, Power 2)', () => {
  it('names five states', () => {
    expect(upsState({ available: false })).toBe('none');
    expect(upsState({ available: false, unreadable: true })).toBe('unreadable');
    expect(upsState({ available: true, on_battery: true })).toBe('cut');
    expect(upsState({ available: true, status: 'OL RB', battery_charge_pct: 90 })).toBe('look');
    expect(upsState({ available: true, status: 'OL', battery_charge_pct: 90 })).toBe('mains');
  });

  it('says it in the reader\'s language', async () => {
    expect(upsSentence({ available: true, on_battery: true, time_left_min: 26.4 })).toBe('Power cut: the NAS runs on its battery, about 26 min left.');
    await setLanguage('de');
    expect(upsSentence({ available: false })).toMatch(/^Keine Batteriesicherung/);
  });
});
