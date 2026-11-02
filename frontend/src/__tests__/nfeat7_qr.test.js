import { describe, it, expect, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), downloadBlob: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('../components/remote-access.js', () => ({ qrSvg: vi.fn(async (text) => `<svg xmlns="http://www.w3.org/2000/svg" data-text="${text}"><rect/></svg>`) }));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { davLink, familyCalendarBody, fillQr, renderFamilyCalendar } from '../components/family-calendar.js';

const flush = () => new Promise((r) => setTimeout(r, 0));
const info = { installed: true, running: true, server: 'nas.local:8093', caldav: 'http://nas.local:8093/remote.php/dav' };

describe('family calendar QR code and iPhone profile (NFEAT-7)', () => {
  it('turns the address into a DAVx⁵ link', () => {
    expect(davLink('http://nas.local:8093/remote.php/dav')).toBe('caldav://nas.local:8093/remote.php/dav');
    expect(davLink('https://nas.example/remote.php/dav')).toBe('caldavs://nas.example/remote.php/dav');
    expect(davLink('')).toBe('');
  });

  it('draws the QR code as parsed SVG', async () => {
    const box = document.createElement('div');
    await fillQr(box, 'caldav://x/remote.php/dav');
    expect(box.querySelector('svg').getAttribute('data-text')).toBe('caldav://x/remote.php/dav');
  });

  it('shows the profile button and a QR code for the address', async () => {
    const box = familyCalendarBody(info, () => {});
    expect(box.querySelector('.fc-qr').getAttribute('role')).toBe('img');
    const btn = [...box.querySelectorAll('button')].find((b) => b.textContent === 'Set up an iPhone or iPad');
    api.downloadBlob.mockResolvedValue('ZettNAS family.mobileconfig');
    btn.click();
    expect(api.downloadBlob).toHaveBeenCalledWith('/api/docker/catalog/office-suite/family/profile', 'ZettNAS family.mobileconfig');
    api.downloadBlob.mockRejectedValue(new Error('nope'));
    btn.click();
    await flush();
    expect(showToast).toHaveBeenCalledWith('nope', 'error');

    api.get.mockResolvedValue(info);
    const mount = document.createElement('div');
    await renderFamilyCalendar(mount);
    await flush();
    await flush();
    expect(mount.querySelector('.fc-qr svg').getAttribute('data-text')).toBe('caldav://nas.local:8093/remote.php/dav');
  });
});
