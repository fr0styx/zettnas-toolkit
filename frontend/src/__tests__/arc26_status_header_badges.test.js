/** The header's LCD and live-data badges, in the reader's language (NUX-20). */
import { describe, it, expect, afterEach } from 'vitest';
import { renderLcdBadge, renderStreamBadge } from '../status-badges.js';
import { setLanguage } from '../i18n.js';

const badge = () => document.createElement('span');

describe('LCD badge', () => {
  afterEach(() => setLanguage('en'));

  it('names each state with its own colour', () => {
    const cases = [
      [{ enabled: false }, 'LCD: turned off', 'lcd-status-disabled', 'disabled'],
      [{ enabled: true, fb_present: false }, 'LCD: not found', 'lcd-status-offline', 'missing'],
      [{ enabled: true, fb_present: true, screen_off: true }, 'LCD: SCREEN OFF', 'lcd-status-disabled', undefined],
      [{ enabled: true, fb_present: true, power: false }, 'LCD: SCREEN OFF', 'lcd-status-disabled', undefined],
      [{ enabled: true, fb_present: true, active: true, fps: 5 }, 'LCD: 5 FPS ACTIVE', 'lcd-status-active', undefined],
      [{ enabled: true, fb_present: true }, 'LCD: IDLE', 'lcd-status-offline', undefined],
    ];
    for (const [data, text, cls, state] of cases) {
      const b = badge();
      renderLcdBadge(b, data);
      expect([b.textContent, b.className, b.dataset.lcdState]).toEqual([text, 'lcd-status-badge ' + cls, state]);
      expect(b.title).not.toBe('');
    }
    const b = badge();
    renderLcdBadge(b, { enabled: true, fb_present: true, active: true, fps: 5 });
    expect(b.title).toBe('LCD direct output is actively streaming at 5 FPS.');
  });

  it('speaks German', async () => {
    await setLanguage('de');
    const b = badge();
    renderLcdBadge(b, { enabled: true, fb_present: true, active: true, fps: 5 });
    expect(b.textContent).toBe('LCD: 5 FPS AKTIV');
    renderLcdBadge(b, { enabled: true, fb_present: true });
    expect(b.textContent).toBe('LCD: LEERLAUF');
  });

  it('does nothing without a badge', () => {
    expect(() => renderLcdBadge(null, { enabled: true })).not.toThrow();
  });
});

describe('live-data badge', () => {
  afterEach(() => setLanguage('en'));

  it('says live or polling', async () => {
    const b = badge();
    renderStreamBadge(b, true);
    expect([b.textContent, b.className]).toEqual(['LIVE SSE', 'header-badge active']);
    renderStreamBadge(b, false);
    expect([b.textContent, b.className]).toEqual(['POLLING', 'header-badge warning']);
    await setLanguage('fr');
    renderStreamBadge(b, false);
    expect(b.textContent).toBe('INTERROGATION');
    expect(() => renderStreamBadge(null, true)).not.toThrow();
  });
});
