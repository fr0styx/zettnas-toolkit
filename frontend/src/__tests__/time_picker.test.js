import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  parseTime24,
  formatTime24,
  formatDisplayTime,
  attachGlassTimePicker,
  initGlassTimePickers,
  openGlassTimePicker,
  closeGlassTimePicker,
} from '../components/time-picker.js';
import { state } from '../state.js';

describe('Glassmorphic Time Picker Component', () => {
  let container;

  beforeEach(() => {
    state.clockFormat = '12';
    document.body.innerHTML = '';
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    closeGlassTimePicker();
    const popover = document.getElementById('glass-time-picker-popover');
    if (popover && popover.parentNode) {
      popover.parentNode.removeChild(popover);
    }
    document.body.innerHTML = '';
  });

  describe('Time Parsing & Formatting Utilities', () => {
    it('correctly parses 24-hour time strings into 12-hour components', () => {
      expect(parseTime24('23:00')).toEqual({
        hours24: 23,
        hours12: 11,
        minutes: 0,
        period: 'PM',
      });

      expect(parseTime24('00:00')).toEqual({
        hours24: 0,
        hours12: 12,
        minutes: 0,
        period: 'AM',
      });

      expect(parseTime24('12:30')).toEqual({
        hours24: 12,
        hours12: 12,
        minutes: 30,
        period: 'PM',
      });

      expect(parseTime24('07:05')).toEqual({
        hours24: 7,
        hours12: 7,
        minutes: 5,
        period: 'AM',
      });

      // Edge cases & null safety
      expect(parseTime24('')).toEqual({
        hours24: 0,
        hours12: 12,
        minutes: 0,
        period: 'AM',
      });
      expect(parseTime24(null)).toEqual({
        hours24: 0,
        hours12: 12,
        minutes: 0,
        period: 'AM',
      });
      expect(parseTime24('invalid')).toEqual({
        hours24: 0,
        hours12: 12,
        minutes: 0,
        period: 'AM',
      });
    });

    it('formats 12-hour components back into standard 24-hour HH:MM format', () => {
      expect(formatTime24(11, 0, 'PM')).toBe('23:00');
      expect(formatTime24(12, 0, 'AM')).toBe('00:00');
      expect(formatTime24(12, 30, 'PM')).toBe('12:30');
      expect(formatTime24(7, 5, 'AM')).toBe('07:05');
      expect(formatTime24(1, 45, 'AM')).toBe('01:45');
    });

    it('formats display time for human readability', () => {
      expect(formatDisplayTime('23:00', '12')).toBe('11:00 PM');
      expect(formatDisplayTime('07:15', '12')).toBe('07:15 AM');
      expect(formatDisplayTime('23:00', '24')).toBe('23:00');
      expect(formatDisplayTime('07:15', '24')).toBe('07:15');
    });
  });

  describe('DOM Enhancement: attachGlassTimePicker', () => {
    it('visually hides native input and inserts a custom glassmorphic trigger', () => {
      const input = document.createElement('input');
      input.type = 'time';
      input.id = 'led-night-start';
      input.value = '23:00';
      container.appendChild(input);

      attachGlassTimePicker(input);

      expect(input.style.display).toBe('none');
      expect(input.dataset.glassEnhanced).toBe('1');

      const trigger = document.getElementById('led-night-start-glass-trigger');
      expect(trigger).not.toBeNull();
      expect(trigger.classList.contains('glass-time-trigger')).toBe(true);
      expect(trigger.getAttribute('aria-haspopup')).toBe('dialog');
      expect(trigger.textContent).toContain('11:00 PM');
    });

    it('updates trigger text when input.value is changed programmatically', () => {
      const input = document.createElement('input');
      input.type = 'time';
      input.id = 'screen-night-start';
      input.value = '23:00';
      container.appendChild(input);

      attachGlassTimePicker(input);
      const trigger = document.getElementById('screen-night-start-glass-trigger');
      expect(trigger.textContent).toContain('11:00 PM');

      // Programmatic assignment
      input.value = '08:30';
      expect(trigger.textContent).toContain('08:30 AM');

      // Programmatic assignment to midnight
      input.value = '00:00';
      expect(trigger.textContent).toContain('12:00 AM');
    });

    it('updates trigger text when input event or change event is dispatched', () => {
      const input = document.createElement('input');
      input.type = 'time';
      input.id = 'ai-schedule-start-input';
      input.value = '01:00';
      container.appendChild(input);

      attachGlassTimePicker(input);
      const trigger = document.getElementById('ai-schedule-start-input-glass-trigger');
      expect(trigger.textContent).toContain('01:00 AM');

      input.value = '15:45';
      input.dispatchEvent(new Event('change'));
      expect(trigger.textContent).toContain('03:45 PM');
    });

    it('is idempotent when called repeatedly on the same element', () => {
      const input = document.createElement('input');
      input.type = 'time';
      input.id = 'test-idempotent';
      input.value = '10:00';
      container.appendChild(input);

      attachGlassTimePicker(input);
      attachGlassTimePicker(input);

      const triggers = container.querySelectorAll('.glass-time-trigger');
      expect(triggers.length).toBe(1);
    });
  });

  describe('Interactive Popover UI & Selection Workflow', () => {
    it('opens popover when trigger is clicked and renders preview and columns', () => {
      const input = document.createElement('input');
      input.type = 'time';
      input.id = 'led-night-start';
      input.value = '23:00';
      container.appendChild(input);

      attachGlassTimePicker(input);
      const trigger = document.getElementById('led-night-start-glass-trigger');

      trigger.click();

      const popover = document.getElementById('glass-time-picker-popover');
      expect(popover).not.toBeNull();
      expect(popover.style.display).toBe('flex');
      expect(popover.getAttribute('aria-hidden')).toBe('false');

      const previewTime = popover.querySelector('#gtp-preview-time');
      const previewPeriod = popover.querySelector('#gtp-preview-period');
      expect(previewTime.textContent).toBe('11:00');
      expect(previewPeriod.textContent).toBe('PM');
    });

    it('updates input value and fires change event when preset chip is clicked', () => {
      const input = document.createElement('input');
      input.type = 'time';
      input.id = 'led-night-start';
      input.value = '23:00';
      container.appendChild(input);

      let changeFired = false;
      input.addEventListener('change', () => {
        changeFired = true;
      });

      attachGlassTimePicker(input);
      const trigger = document.getElementById('led-night-start-glass-trigger');
      trigger.click();

      const popover = document.getElementById('glass-time-picker-popover');
      const preset07 = popover.querySelector('.gtp-preset-btn[data-preset="07:00"]');
      expect(preset07).not.toBeNull();

      preset07.click();

      expect(input.value).toBe('07:00');
      expect(changeFired).toBe(true);
      expect(trigger.textContent).toContain('07:00 AM');
    });

    it('allows picking specific hour, minute, and period interactively', () => {
      const input = document.createElement('input');
      input.type = 'time';
      input.id = 'led-night-end';
      input.value = '07:00';
      container.appendChild(input);

      attachGlassTimePicker(input);
      const trigger = document.getElementById('led-night-end-glass-trigger');
      trigger.click();

      const popover = document.getElementById('glass-time-picker-popover');

      // Click hour 9
      const hourBtn = popover.querySelector('.gtp-item-btn[data-hour="9"]');
      expect(hourBtn).not.toBeNull();
      hourBtn.click();

      // Click minute 45
      const minBtn = popover.querySelector('.gtp-item-btn[data-minute="45"]');
      expect(minBtn).not.toBeNull();
      minBtn.click();

      // Click PM
      const pmBtn = popover.querySelector('.gtp-period-btn[data-period="PM"]');
      expect(pmBtn).not.toBeNull();
      pmBtn.click();

      expect(input.value).toBe('21:45');
      expect(trigger.textContent).toContain('09:45 PM');
    });

    it('closes popover on Done button click, Escape key, or outside pointerdown', () => {
      const input = document.createElement('input');
      input.type = 'time';
      input.id = 'led-night-start';
      input.value = '23:00';
      container.appendChild(input);

      attachGlassTimePicker(input);
      const trigger = document.getElementById('led-night-start-glass-trigger');
      trigger.click();

      const popover = document.getElementById('glass-time-picker-popover');
      expect(popover.style.display).toBe('flex');

      // Click Done
      const doneBtn = popover.querySelector('#gtp-btn-done');
      expect(doneBtn).not.toBeNull();
      doneBtn.click();

      expect(popover.style.display).toBe('none');

      // Reopen and test Escape key
      trigger.click();
      expect(popover.style.display).toBe('flex');

      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      expect(popover.style.display).toBe('none');

      // Reopen and test outside pointerdown
      trigger.click();
      expect(popover.style.display).toBe('flex');

      document.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }));
      expect(popover.style.display).toBe('none');
    });

    it('sets current time when Current Time button is clicked', () => {
      const input = document.createElement('input');
      input.type = 'time';
      input.id = 'test-now-input';
      input.value = '12:00';
      container.appendChild(input);

      attachGlassTimePicker(input);
      const trigger = document.getElementById('test-now-input-glass-trigger');
      trigger.click();

      const popover = document.getElementById('glass-time-picker-popover');
      const nowBtn = popover.querySelector('#gtp-btn-now');
      expect(nowBtn).not.toBeNull();

      nowBtn.click();

      // Input value should be a valid HH:MM
      expect(input.value).toMatch(/^([01]\d|2[0-3]):[0-5]\d$/);
    });
  });

  describe('Bulk Initialization: initGlassTimePickers', () => {
    it('scans and initializes multiple night schedule and AI schedule inputs', () => {
      container.innerHTML = `
        <div id="tab-led">
          <input type="time" id="led-night-start" value="23:00">
          <input type="time" id="led-night-end" value="07:00">
        </div>
        <div id="tab-screen">
          <input type="time" id="screen-night-start" value="22:30">
          <input type="time" id="screen-night-end" value="06:30">
        </div>
        <div id="mgmt-sec-ai">
          <input type="time" id="ai-schedule-start-input" value="01:00">
          <input type="time" id="ai-schedule-end-input" value="06:00">
        </div>
      `;

      initGlassTimePickers(container);

      const triggers = container.querySelectorAll('.glass-time-trigger');
      expect(triggers.length).toBe(6);

      const ledStartTrigger = document.getElementById('led-night-start-glass-trigger');
      expect(ledStartTrigger).not.toBeNull();
      expect(ledStartTrigger.textContent).toContain('11:00 PM');

      const ledEndTrigger = document.getElementById('led-night-end-glass-trigger');
      expect(ledEndTrigger).not.toBeNull();
      expect(ledEndTrigger.textContent).toContain('07:00 AM');

      const aiStartTrigger = document.getElementById('ai-schedule-start-input-glass-trigger');
      expect(aiStartTrigger).not.toBeNull();
      expect(aiStartTrigger.textContent).toContain('01:00 AM');
    });

    it('formats trigger text in 24-hour mode when state.clockFormat is 24', () => {
      state.clockFormat = '24';
      container.innerHTML = `
        <input type="time" id="screen-night-start" value="23:00">
      `;
      initGlassTimePickers(container);

      const trigger = document.getElementById('screen-night-start-glass-trigger');
      expect(trigger).not.toBeNull();
      expect(trigger.textContent).toContain('23:00');
    });
  });
});
