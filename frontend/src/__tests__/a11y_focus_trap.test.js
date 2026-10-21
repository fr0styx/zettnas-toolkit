import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { trapFocus, isFocusableElementVisible } from '../utils.js';

describe('Item 3.3: WCAG 2.2 Focus Trap Visibility Filter', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    container.id = 'modal-container';
    document.body.appendChild(container);
  });

  afterEach(() => {
    container.remove();
    document.body.innerHTML = '';
  });

  it('isFocusableElementVisible correctly filters visible vs invisible elements', () => {
    container.innerHTML = `
      <button id="btn-visible">Visible</button>
      <button id="btn-disabled" disabled>Disabled</button>
      <button id="btn-aria-hidden" aria-hidden="true">Aria Hidden</button>
      <button id="btn-inline-hidden" style="display: none;">Inline Hidden</button>
      <div hidden><button id="btn-parent-hidden">Parent Hidden</button></div>
      <div style="display: none;"><button id="btn-ancestor-none">Ancestor None</button></div>
      <div class="tab-pane"><button id="btn-inactive-tab">Inactive Tab</button></div>
      <div class="tab-pane active"><button id="btn-active-tab">Active Tab</button></div>
    `;

    expect(isFocusableElementVisible(document.getElementById('btn-visible'))).toBe(true);
    expect(isFocusableElementVisible(document.getElementById('btn-disabled'))).toBe(false);
    expect(isFocusableElementVisible(document.getElementById('btn-aria-hidden'))).toBe(false);
    expect(isFocusableElementVisible(document.getElementById('btn-inline-hidden'))).toBe(false);
    expect(isFocusableElementVisible(document.getElementById('btn-parent-hidden'))).toBe(false);
    expect(isFocusableElementVisible(document.getElementById('btn-ancestor-none'))).toBe(false);
    expect(isFocusableElementVisible(document.getElementById('btn-inactive-tab'))).toBe(false);
    expect(isFocusableElementVisible(document.getElementById('btn-active-tab'))).toBe(true);
  });

  it('trapFocus cycles focus strictly between active/visible elements, skipping hidden tab panes', () => {
    container.innerHTML = `
      <button id="btn-tab-1">Tab 1 Switcher</button>
      <div class="tab-pane active" id="pane-1">
        <input id="input-active" type="text" value="Active Input" />
      </div>
      <div class="tab-pane" id="pane-2">
        <input id="input-hidden" type="text" value="Hidden Input" />
        <button id="btn-hidden">Hidden Action</button>
      </div>
      <button id="btn-save">Save Modal</button>
    `;

    const unbind = trapFocus(container);

    const btnTab1 = document.getElementById('btn-tab-1');
    const inputActive = document.getElementById('input-active');
    const btnSave = document.getElementById('btn-save');

    // Focus last visible item (btnSave) and press Tab -> should wrap to btnTab1, NOT hidden pane 2 elements
    btnSave.focus();
    const tabEvent = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    container.dispatchEvent(tabEvent);
    expect(document.activeElement).toBe(btnTab1);

    // Press Shift+Tab on first element -> should wrap to last visible element (btnSave)
    btnTab1.focus();
    const shiftTabEvent = new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true });
    container.dispatchEvent(shiftTabEvent);
    expect(document.activeElement).toBe(btnSave);

    unbind();
  });
});
