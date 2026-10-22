import { describe, it, expect } from 'vitest';
import { closestPath } from '../components/fm-favorites.js';

describe('Quick Locations: the current place', () => {
  const places = ['/mnt/user', '/mnt/user/appdata', '/boot', '/mnt/user/.RecycleBin'];
  it('is the closest containing place, not every parent', () => {
    expect(closestPath(places, '/mnt/user/appdata')).toBe('/mnt/user/appdata');
    expect(closestPath(places, '/mnt/user/appdata/plex/')).toBe('/mnt/user/appdata');
    expect(closestPath(places, '/mnt/user/vault/Media')).toBe('/mnt/user');
    expect(closestPath(places, '/mnt/user/appdata2')).toBe('/mnt/user');
    expect(closestPath(places, '/tmp')).toBeNull();
  });
});
