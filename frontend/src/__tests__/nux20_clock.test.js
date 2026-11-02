/** NUX-20: the clock widget's time-zone badge title comes from the locale strings. */
import { describe, it, expect, vi } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(() => Promise.resolve({})), post: vi.fn(() => Promise.resolve({})), put: vi.fn(() => Promise.resolve({})) } }));

import { saveWidgetConfig, updateClock } from '../components/widgets.js';

describe('clock widget text (NUX-20)', () => {
  it('names the chosen time zone in the badge title', () => {
    document.body.innerHTML = '<div id="widget-clock"><span id="w-clock-time"></span><span id="w-clock-date"></span><span id="w-clock-tz"></span></div>';
    saveWidgetConfig({ clockTimezone: 'Europe/Berlin', clockFormat: '24' });
    updateClock();
    const title = document.getElementById('w-clock-tz').title;
    expect(title).toContain('Time zone: Europe/Berlin');
    expect(title).toContain('Click to change it.');
  });
});
