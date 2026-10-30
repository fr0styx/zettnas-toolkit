import { describe, it, expect, vi, beforeEach } from 'vitest';

describe("each person's time zone, and a server zone from an administrator's browser", () => {
  beforeEach(async () => {
    vi.restoreAllMocks();
    localStorage.clear();
    (await import('../time-zone-prefs.js'))._resetForTests();
  });

  it('auto is the browser zone', async () => {
    const { resolveZone, browserZone } = await import('../time-zone-prefs.js');
    expect(resolveZone('auto')).toBe(browserZone());
    expect(resolveZone('')).toBe(browserZone());
    expect(resolveZone('Asia/Tokyo')).toBe('Asia/Tokyo');
  });

  it("gives a server without a zone the first administrator's, once per page", async () => {
    const { api } = await import('../api.js');
    const { detectServerZone, browserZone } = await import('../time-zone-prefs.js');
    const get = vi.spyOn(api, 'get').mockResolvedValue({ timezone: '' });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ timezone: browserZone() });

    expect(await detectServerZone({ scopes: ['files:read'] })).toBe(null); // not an administrator
    expect(get).not.toHaveBeenCalled();
    await detectServerZone({ scopes: ['system:config'] });
    expect(post).toHaveBeenCalledWith('/api/system/identity/detected-timezone', { timezone: browserZone() });
    await detectServerZone({ scopes: ['*'] });
    expect(post).toHaveBeenCalledTimes(1);
  });

  it('leaves a zone the server already has, and survives a failed call', async () => {
    const { api } = await import('../api.js');
    const { detectServerZone, _resetForTests, savePersonZone } = await import('../time-zone-prefs.js');
    vi.spyOn(api, 'get').mockResolvedValue({ timezone: 'America/New_York' });
    const post = vi.spyOn(api, 'post');
    expect(await detectServerZone({ scopes: ['*'] })).toBe(null);
    expect(post).not.toHaveBeenCalled();
    _resetForTests();
    api.get.mockRejectedValue(new Error('down'));
    expect(await detectServerZone({ scopes: ['*'] })).toBe(null);
    expect(await detectServerZone(null)).toBe(null);
    vi.spyOn(api, 'put').mockRejectedValue(new Error('down'));
    expect(await savePersonZone('Asia/Tokyo', '12')).toBe(null);
  });

  it("shows the account's clock on a new device and moves an old browser choice onto the account", async () => {
    const { api } = await import('../api.js');
    const put = vi.spyOn(api, 'put').mockResolvedValue({});
    const { applyPersonClock, loadWidgetConfig, saveWidgetConfig } = await import('../components/widgets.js');
    const { ZettEventBus } = await import('../event-bus.js');
    const seen = vi.fn();
    ZettEventBus.on('clock:changed', seen);

    applyPersonClock({ timezone: 'Asia/Tokyo', clock_format: '12' });
    expect(loadWidgetConfig().clockTimezone).toBe('Asia/Tokyo');
    expect(loadWidgetConfig().clockFormat).toBe('12');
    expect(seen).toHaveBeenCalledWith({ zone: 'Asia/Tokyo', format: '12' }, expect.anything());
    seen.mockClear();
    applyPersonClock({ timezone: 'Asia/Tokyo', clock_format: '12' }); // nothing new
    expect(seen).not.toHaveBeenCalled();
    expect(put).not.toHaveBeenCalled();

    saveWidgetConfig({ clockTimezone: 'Europe/Paris', clockFormat: '24' });
    applyPersonClock({}); // the account has none yet
    expect(put).toHaveBeenCalledWith('/api/auth/me/preferences', { timezone: 'Europe/Paris', clock_format: '24' });
    put.mockClear();
    saveWidgetConfig({ clockTimezone: 'auto' });
    applyPersonClock(null);
    expect(put).not.toHaveBeenCalled();
  });
});
