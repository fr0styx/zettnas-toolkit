/** Lagoon contrast (e2e a11y on 6fc6e3c): the active 12/24 h button uses the theme's contrast colour. */
import { describe, it, expect, beforeEach } from 'vitest';
import { resetTimezoneChoice, saveWidgetConfig, updateTzModalPreview } from '../components/widgets.js';

describe('time format buttons', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <input id="tz-search-input"><div id="tz-items-list"></div>
      <div id="modal-tz-preview-time"></div><div id="modal-tz-preview-date"></div>
      <button id="btn-tz-fmt-12"></button><button id="btn-tz-fmt-24"></button>`;
  });

  it('paint the chosen one in the contrast colour of the brand, never black', () => {
    const b12 = document.getElementById('btn-tz-fmt-12');
    const b24 = document.getElementById('btn-tz-fmt-24');
    saveWidgetConfig({ clockTimezone: 'auto', clockFormat: '24' });
    resetTimezoneChoice();
    updateTzModalPreview();
    expect(b24.style.color).toBe('var(--accent-contrast-fg)');
    expect(b12.style.color).toBe('var(--zn-text-muted)');
    saveWidgetConfig({ clockTimezone: 'auto', clockFormat: '12' });
    resetTimezoneChoice();
    updateTzModalPreview();
    expect(b12.style.color).toBe('var(--accent-contrast-fg)');
    expect(b24.style.color).toBe('var(--zn-text-muted)');
  });
});
