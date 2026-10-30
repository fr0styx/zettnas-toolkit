import { describe, it, expect, beforeEach } from 'vitest';
import { renderTimezoneList, onTimezoneListKey, resetTimezoneChoice, saveWidgetConfig } from '../components/widgets.js';

function key(list, k) {
  const e = new KeyboardEvent('keydown', { key: k, cancelable: true });
  Object.defineProperty(e, 'currentTarget', { value: list });
  onTimezoneListKey(e);
  return e;
}

describe('time-zone list by keyboard (NUX-8)', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <input id="tz-search-input">
      <div id="tz-items-list" tabindex="0" role="listbox"></div>
      <div id="modal-tz-preview-time"></div><div id="modal-tz-preview-date"></div>
      <button id="btn-tz-fmt-12"></button><button id="btn-tz-fmt-24"></button>`;
    saveWidgetConfig({ clockTimezone: 'auto', clockFormat: '24' });
    resetTimezoneChoice();
  });

  it('rows are options, the chosen one is selected and active', () => {
    const list = document.getElementById('tz-items-list');
    const auto = list.querySelector('[data-tz-id="auto"]');
    expect(auto.getAttribute('role')).toBe('option');
    expect(auto.getAttribute('aria-selected')).toBe('true');
    expect(list.getAttribute('aria-activedescendant')).toBe(auto.id);
  });

  it('arrows move, Enter picks, Undo puts the saved zone back', () => {
    const list = document.getElementById('tz-items-list');
    expect(key(list, 'ArrowDown').defaultPrevented).toBe(true);
    const next = document.getElementById(list.getAttribute('aria-activedescendant'));
    expect(next.dataset.tzId).toBe('UTC');
    key(list, 'Enter');
    expect(list.querySelector('[aria-selected="true"]').dataset.tzId).toBe('UTC');
    key(list, 'End');
    expect(document.getElementById(list.getAttribute('aria-activedescendant'))).toBe(list.lastElementChild);
    expect(key(list, 'a').defaultPrevented).toBe(false);
    resetTimezoneChoice();
    expect(list.querySelector('[aria-selected="true"]').dataset.tzId).toBe('auto');
  });

  it('12/24 h are radios', () => {
    resetTimezoneChoice();
    expect(document.getElementById('btn-tz-fmt-24').getAttribute('aria-checked')).toBe('true');
    expect(document.getElementById('btn-tz-fmt-12').getAttribute('aria-checked')).toBe('false');
  });
});
