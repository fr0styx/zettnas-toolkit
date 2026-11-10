import { describe, it, expect, vi } from 'vitest';
import { funnelStepsHtml, recheckWhileOpen, RECHECK_MS, RECHECK_FOR_MS } from '../components/management/funnel-steps.js';

const NOT = { connected: true, https: false, funnel: false, ready: false, headscale: false, dns_url: 'https://login.tailscale.com/admin/dns', approve_url: 'https://login.tailscale.com/f/funnel?node=n1CNTRL' };

describe('the steps only the tailnet owner can do (Funnel)', () => {
  it('lists both with a link each, ticks the done one, and says what waits', () => {
    const html = funnelStepsHtml(NOT, 'Kiboto puts jellyfin on the internet as soon as both are done.');
    expect(html).toContain('Turn on HTTPS certificates');
    expect(html).toContain('href="https://login.tailscale.com/admin/dns"');
    expect(html).toContain('href="https://login.tailscale.com/f/funnel?node=n1CNTRL"');
    expect(html).toContain('jellyfin');
    const half = funnelStepsHtml({ ...NOT, https: true });
    expect(half).toContain('is-done');
    expect(half.match(/href=/g)).toHaveLength(1);
  });

  it('says nothing once ready or without Tailscale, and explains Headscale', () => {
    expect(funnelStepsHtml({ ...NOT, ready: true })).toBe('');
    expect(funnelStepsHtml({ ...NOT, connected: false })).toBe('');
    expect(funnelStepsHtml(null)).toBe('');
    expect(funnelStepsHtml({ ...NOT, headscale: true })).toContain('Headscale');
  });

  it('looks again while steps are open, for a while only', () => {
    const timers = { setTimeout: vi.fn(() => 7), clearTimeout: vi.fn() };
    const reload = vi.fn();
    expect(recheckWhileOpen(NOT, reload, timers)).toBe(7);
    expect(timers.setTimeout).toHaveBeenCalledWith(expect.any(Function), RECHECK_MS);
    timers.setTimeout.mock.calls[0][0]();
    expect(reload).toHaveBeenCalled();
    expect(recheckWhileOpen({ ...NOT, ready: true }, reload, timers)).toBeNull();
    expect(recheckWhileOpen({ ...NOT, headscale: true }, reload, timers)).toBeNull();
    expect(recheckWhileOpen(NOT, reload, timers, Date.now() - RECHECK_FOR_MS - 1)).toBeNull();
  });
});
