import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { SUBPANE_MAP } from '../components/management.js';

const html = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');

/** The markup of one element, its <div> tags balanced. */
function element(id) {
  const start = html.indexOf(`<div id="${id}"`);
  let depth = 0;
  for (const m of html.slice(start).matchAll(/<div\b|<\/div>/g)) {
    depth += m[0] === '<div' ? 1 : -1;
    if (depth === 0) return html.slice(start, start + m.index + m[0].length);
  }
  return '';
}

describe('Time, Language & Region lives in Settings (APP-C)', () => {
  it('its tab and pane are in Settings, not in Appearance', () => {
    const settings = element('mgmt-sec-system-group');
    const appearance = element('mgmt-sec-wallpaper');
    expect(settings).toContain('data-tab-target="mgmt-pane-language"');
    expect(settings).toContain('id="mgmt-pane-language"');
    expect(appearance).not.toContain('mgmt-pane-language');
    expect(element('mgmt-pane-security')).not.toContain('mgmt-pane-language');
  });

  it('every way in opens it there', () => {
    for (const key of ['mgmt-sec-language', 'mgmt-pane-language', 'timezone', 'clock', 'time', 'language', 'region']) {
      expect(SUBPANE_MAP[key]).toEqual({ section: 'mgmt-sec-system-group', pane: 'mgmt-pane-language' });
    }
  });
});

describe('Calendar has a section of its own (APP-C)', () => {
  it('its pane is in the Calendar section, which the sidebar opens', () => {
    expect(element('mgmt-sec-calendar')).toContain('id="mgmt-pane-calendar"');
    expect(element('mgmt-sec-wallpaper')).not.toContain('mgmt-pane-calendar');
    expect(html).toContain('data-mgmt-target="mgmt-sec-calendar"');
    for (const key of ['mgmt-sec-calendar', 'mgmt-pane-calendar', 'calendar']) {
      expect(SUBPANE_MAP[key]).toEqual({ section: 'mgmt-sec-calendar', pane: 'mgmt-pane-calendar' });
    }
  });
});
