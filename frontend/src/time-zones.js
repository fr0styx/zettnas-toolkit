// One list of time zones for Settings and the setup wizard (NUX-22): every zone the browser
// knows, named in the person's language ("Mitteleuropäische Zeit", "Tokyo"), grouped by region.
import { currentLocale } from './format.js';

const REGIONS = { America: 'Americas', Europe: 'Europe', Asia: 'Asia', Australia: 'Pacific', Pacific: 'Pacific' };
const _cache = new Map();

/** Every IANA zone, UTC first; a short list when the browser can't list them. */
export function allZones() {
  let zones;
  try {
    zones = Intl.supportedValuesOf('timeZone');
  } catch {
    zones = ['UTC', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Los_Angeles', 'Asia/Tokyo', 'Australia/Sydney'];
  }
  return ['UTC', ...zones.filter((z) => z !== 'UTC')];
}

/** "Tokyo" from "Asia/Tokyo", "Buenos Aires" from "America/Argentina/Buenos_Aires". */
export function cityOf(id) {
  return String(id).split('/').pop().replace(/_/g, ' ');
}

/** The zone's name in the locale ("Central European Time"), or '' when the browser has none. */
export function zoneName(id, locale = currentLocale()) {
  try {
    const part = new Intl.DateTimeFormat(locale, { timeZone: id, timeZoneName: 'longGeneric' })
      .formatToParts(new Date())
      .find((p) => p.type === 'timeZoneName');
    return part ? part.value : '';
  } catch {
    return '';
  }
}

/** [{id, name, region, country}] in the locale: name is the city, country the zone's name. */
export function zoneCatalog(locale = currentLocale()) {
  if (_cache.has(locale)) return _cache.get(locale);
  const list = allZones().map((id) => ({
    id,
    name: id === 'UTC' ? 'UTC' : cityOf(id),
    region: id === 'UTC' || id.startsWith('Etc/') ? 'UTC' : REGIONS[id.split('/')[0]] || 'Other',
    country: zoneName(id, locale),
  }));
  _cache.set(locale, list);
  return list;
}
