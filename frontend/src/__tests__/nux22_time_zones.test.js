import { describe, it, expect, vi } from 'vitest';

vi.mock('../i18n.js', () => ({ getLanguage: () => 'de', t: (k, f) => f }));

const { allZones, cityOf, zoneCatalog, zoneName } = await import('../time-zones.js');

describe('one list of time zones (NUX-22)', () => {
  it('has every zone the browser knows, UTC first, once', () => {
    const zones = allZones();
    expect(zones[0]).toBe('UTC');
    expect(zones.filter((z) => z === 'UTC')).toHaveLength(1);
    expect(zones).toContain('Europe/Berlin');
    expect(zones.length).toBeGreaterThan(300);
  });

  it('names cities and zones in the language', () => {
    expect(cityOf('America/Argentina/Buenos_Aires')).toBe('Buenos Aires');
    const berlin = zoneCatalog('de-DE').find((z) => z.id === 'Europe/Berlin');
    expect(berlin).toMatchObject({ name: 'Berlin', region: 'Europe' });
    expect(berlin.country).toMatch(/Mitteleurop/);
    expect(zoneCatalog('de-DE')).toBe(zoneCatalog('de-DE')); // built once per language
    expect(zoneCatalog('de-DE').find((z) => z.id === 'Africa/Cairo').region).toBe('Other');
    expect(zoneName('Not/AZone')).toBe('');
  });
});
