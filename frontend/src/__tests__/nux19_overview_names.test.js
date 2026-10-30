import { describe, it, expect, vi } from 'vitest';

vi.mock('../i18n.js', () => ({
  t: (key, fallback, params = {}) => String(fallback).replace(/\{(\w+)\}/g, (m, k) => (k in params ? params[k] : m)),
}));

const { itemText, statusHtml } = await import('../components/management/overview.js');

describe('Overview items (NUX-19)', () => {
  it('names a stalled service by what it does', () => {
    expect(itemText({ kind: 'service_stalled', subject: 'SmartPoller' })).toBe(
      'The drive health check service has stopped responding. Restart ZettNAS if it does not recover.',
    );
    expect(itemText({ kind: 'service_stalled', subject: 'NewThing' })).toContain('The NewThing service');
  });

  it('gives an unknown kind a sentence, not its id alone', () => {
    expect(itemText({ kind: 'mystery', subject: 'x' })).toBe('Something needs attention: x.');
    expect(itemText({ kind: 'mystery' })).toBe('Something needs attention: mystery.');
  });

  it('labels each Open button with its item', () => {
    const html = statusHtml({ ok: false, items: [{ kind: 'on_battery', level: 'warning', open: 'power' }] });
    if (html.includes('data-ov-open')) expect(html).toContain('aria-label="Open: The server is running on battery power."');
  });
});
