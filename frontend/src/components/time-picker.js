/**
 * ZettNAS Toolkit - Glassmorphic Time Picker Component
 * Provides a responsive, accessible, theme-aware time picker dropdown in the OS design language.
 * Replaces native browser OS time picker popups with a frosted glass wheel/column popover.
 * Complies with Modern Web Guidance (resilient-context-menus-and-nested-dropdowns).
 */

import { state } from '../state.js';

let _activePopover = null;
let _activeInput = null;
let _activeTrigger = null;
let _listenersBound = false;

/**
 * Parses 24-hour time string ("23:00") into numeric components.
 */
export function parseTime24(timeStr) {
  if (!timeStr || typeof timeStr !== 'string') {
    return { hours24: 0, hours12: 12, minutes: 0, period: 'AM' };
  }
  const parts = timeStr.trim().split(':');
  let h = parseInt(parts[0], 10);
  let m = parseInt(parts[1], 10);
  if (isNaN(h) || h < 0 || h > 23) h = 0;
  if (isNaN(m) || m < 0 || m > 59) m = 0;

  const period = h >= 12 ? 'PM' : 'AM';
  let h12 = h % 12;
  if (h12 === 0) h12 = 12;

  return { hours24: h, hours12: h12, minutes: m, period };
}

/**
 * Formats 12-hour components back into standard HTML5 "HH:MM" 24-hour format.
 */
export function formatTime24(hours12, minutes, period) {
  let h = parseInt(hours12, 10);
  if (isNaN(h) || h < 1 || h > 12) h = 12;
  const m = Math.min(59, Math.max(0, parseInt(minutes, 10) || 0));

  let h24 = h;
  if (period === 'AM') {
    h24 = h === 12 ? 0 : h;
  } else {
    h24 = h === 12 ? 12 : h + 12;
  }
  return `${String(h24).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

/**
 * Formats 24h string into human-friendly 12-hour or 24-hour string according to user preference.
 */
export function formatDisplayTime(timeStr, formatPreference = null) {
  const { hours12, hours24, minutes, period } = parseTime24(timeStr);
  const is12 = formatPreference === '12' || (formatPreference === null && state?.clockFormat !== '24');
  const mm = String(minutes).padStart(2, '0');

  if (is12) {
    const hh = String(hours12).padStart(2, '0');
    return `${hh}:${mm} ${period}`;
  } else {
    const hh = String(hours24).padStart(2, '0');
    return `${hh}:${mm}`;
  }
}

/**
 * Ensures global dismiss listeners are registered once.
 */
function bindGlobalEvents() {
  if (_listenersBound) return;
  _listenersBound = true;

  document.addEventListener('pointerdown', (e) => {
    if (!_activePopover || _activePopover.style.display === 'none') return;
    if (_activePopover.contains(e.target)) return;
    if (_activeTrigger && _activeTrigger.contains(e.target)) return;
    closeGlassTimePicker();
  });

  window.addEventListener('resize', () => {
    if (_activePopover && _activePopover.style.display !== 'none' && _activeTrigger) {
      positionPopover(_activePopover, _activeTrigger);
    }
  });

  window.addEventListener('scroll', () => {
    if (_activePopover && _activePopover.style.display !== 'none' && _activeTrigger) {
      positionPopover(_activePopover, _activeTrigger);
    }
  }, true);

  document.addEventListener('keydown', (e) => {
    if (!_activePopover || _activePopover.style.display === 'none') return;
    if (e.key === 'Escape') {
      e.preventDefault();
      closeGlassTimePicker();
    }
  });
}

/**
 * Calculates resilient boundary clamping so popover never overflows viewport edges.
 */
function positionPopover(popover, trigger) {
  if (!popover || !trigger) return;
  const triggerRect = trigger.getBoundingClientRect();
  const popoverRect = popover.getBoundingClientRect();
  const width = popoverRect.width || 256;
  const height = popoverRect.height || 280;

  let left = triggerRect.left;
  let top = triggerRect.bottom + 6;

  // Viewport right clamping
  if (left + width > window.innerWidth - 12) {
    left = window.innerWidth - width - 12;
  }
  // Viewport left clamping
  if (left < 12) {
    left = 12;
  }

  // Flip upwards if overflowing bottom
  if (top + height > window.innerHeight - 12) {
    const flippedTop = triggerRect.top - height - 6;
    if (flippedTop >= 12) {
      top = flippedTop;
    }
  }

  popover.style.left = `${Math.round(left)}px`;
  popover.style.top = `${Math.round(top)}px`;
}

/**
 * Creates or retrieves the singleton popover container.
 */
function getOrCreatePopover() {
  let popover = document.getElementById('glass-time-picker-popover');
  if (!popover) {
    popover = document.createElement('div');
    popover.id = 'glass-time-picker-popover';
    popover.className = 'glass-time-popover';
    popover.style.display = 'none';
    popover.setAttribute('role', 'dialog');
    popover.setAttribute('aria-label', 'Time Selector');
    document.body.appendChild(popover);
  }
  return popover;
}

/**
 * Closes the active glassmorphic time picker popover.
 */
export function closeGlassTimePicker() {
  if (_activePopover) {
    _activePopover.style.display = 'none';
    _activePopover.setAttribute('aria-hidden', 'true');
  }
  if (_activeTrigger) {
    _activeTrigger.classList.remove('active');
    _activeTrigger.setAttribute('aria-expanded', 'false');
  }
  _activeInput = null;
  _activeTrigger = null;
}

/**
 * Opens and renders the glassmorphic time picker dropdown for a given input element.
 */
export function openGlassTimePicker(inputEl, triggerEl) {
  if (!inputEl) return;
  bindGlobalEvents();

  if (_activeInput === inputEl && _activePopover && _activePopover.style.display !== 'none') {
    closeGlassTimePicker();
    return;
  }

  _activeInput = inputEl;
  _activeTrigger = triggerEl;

  if (triggerEl) {
    triggerEl.classList.add('active');
    triggerEl.setAttribute('aria-expanded', 'true');
  }

  const popover = getOrCreatePopover();
  _activePopover = popover;

  let currentParsed = parseTime24(inputEl.value || '12:00');
  let selectedH12 = currentParsed.hours12;
  let selectedMin = currentParsed.minutes;
  let selectedPeriod = currentParsed.period;

  function commitTime() {
    const new24 = formatTime24(selectedH12, selectedMin, selectedPeriod);
    if (inputEl.value !== new24) {
      inputEl.value = new24;
      inputEl.dispatchEvent(new Event('input', { bubbles: true }));
      inputEl.dispatchEvent(new Event('change', { bubbles: true }));
    }
    updateTriggerText(triggerEl, new24);
  }

  function renderPopoverContent() {
    const dispTime = `${String(selectedH12).padStart(2, '0')}:${String(selectedMin).padStart(2, '0')}`;
    const minutesList = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55];

    popover.innerHTML = `
      <div class="gtp-header">
        <div class="gtp-preview">
          <span class="gtp-preview-time" id="gtp-preview-time">${dispTime}</span>
          <span class="gtp-preview-period" id="gtp-preview-period">${selectedPeriod}</span>
        </div>
        <div class="gtp-presets-row">
          <button type="button" class="gtp-preset-btn" data-preset="23:00">23:00 (11P)</button>
          <button type="button" class="gtp-preset-btn" data-preset="00:00">00:00 (12A)</button>
          <button type="button" class="gtp-preset-btn" data-preset="07:00">07:00 (7A)</button>
          <button type="button" class="gtp-preset-btn" data-preset="08:00">08:00 (8A)</button>
        </div>
      </div>

      <div class="gtp-columns-grid">
        <!-- Column 1: Hours -->
        <div class="gtp-column">
          <div class="gtp-col-label">Hour</div>
          <div class="gtp-scroll-list" id="gtp-hours-list">
            ${Array.from({ length: 12 }, (_, i) => i + 1).map((h) => {
              const activeCls = h === selectedH12 ? 'active' : '';
              return `<button type="button" class="gtp-item-btn ${activeCls}" data-hour="${h}">${String(h).padStart(2, '0')}</button>`;
            }).join('')}
          </div>
        </div>

        <!-- Column 2: Minutes -->
        <div class="gtp-column">
          <div class="gtp-col-label">Minute</div>
          <div class="gtp-scroll-list" id="gtp-minutes-list">
            ${minutesList.map((m) => {
              const activeCls = m === selectedMin ? 'active' : '';
              return `<button type="button" class="gtp-item-btn ${activeCls}" data-minute="${m}">${String(m).padStart(2, '0')}</button>`;
            }).join('')}
          </div>
        </div>

        <!-- Column 3: AM / PM -->
        <div class="gtp-column">
          <div class="gtp-col-label">Period</div>
          <div class="gtp-period-col">
            <button type="button" class="gtp-period-btn ${selectedPeriod === 'AM' ? 'active' : ''}" data-period="AM">AM</button>
            <button type="button" class="gtp-period-btn ${selectedPeriod === 'PM' ? 'active' : ''}" data-period="PM">PM</button>
          </div>
        </div>
      </div>

      <div class="gtp-footer">
        <button type="button" class="gtp-now-btn" id="gtp-btn-now">Current Time</button>
        <button type="button" class="gtp-done-btn" id="gtp-btn-done">Done</button>
      </div>
    `;

    // Presets
    popover.querySelectorAll('.gtp-preset-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const pVal = btn.dataset.preset;
        const pParsed = parseTime24(pVal);
        selectedH12 = pParsed.hours12;
        selectedMin = pParsed.minutes;
        selectedPeriod = pParsed.period;
        commitTime();
        renderPopoverContent();
      });
    });

    // Hours click
    popover.querySelectorAll('#gtp-hours-list .gtp-item-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        selectedH12 = parseInt(btn.dataset.hour, 10);
        commitTime();
        renderPopoverContent();
      });
    });

    // Minutes click
    popover.querySelectorAll('#gtp-minutes-list .gtp-item-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        selectedMin = parseInt(btn.dataset.minute, 10);
        commitTime();
        renderPopoverContent();
      });
    });

    // Period click
    popover.querySelectorAll('.gtp-period-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        selectedPeriod = btn.dataset.period;
        commitTime();
        renderPopoverContent();
      });
    });

    // Current time
    const nowBtn = popover.querySelector('#gtp-btn-now');
    if (nowBtn) {
      nowBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const now = new Date();
        const nowH = now.getHours();
        const nowM = Math.round(now.getMinutes() / 5) * 5 % 60;
        selectedPeriod = nowH >= 12 ? 'PM' : 'AM';
        selectedH12 = nowH % 12 || 12;
        selectedMin = nowM;
        commitTime();
        renderPopoverContent();
      });
    }

    // Done
    const doneBtn = popover.querySelector('#gtp-btn-done');
    if (doneBtn) {
      doneBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        commitTime();
        closeGlassTimePicker();
      });
    }

    // Auto-scroll columns to selected items
    const activeHourBtn = popover.querySelector('#gtp-hours-list .active');
    if (activeHourBtn && typeof activeHourBtn.scrollIntoView === 'function') {
      activeHourBtn.scrollIntoView({ block: 'nearest' });
    }
    const activeMinBtn = popover.querySelector('#gtp-minutes-list .active');
    if (activeMinBtn && typeof activeMinBtn.scrollIntoView === 'function') {
      activeMinBtn.scrollIntoView({ block: 'nearest' });
    }
  }

  renderPopoverContent();
  popover.style.display = 'flex';
  popover.setAttribute('aria-hidden', 'false');

  if (triggerEl) {
    positionPopover(popover, triggerEl);
  }
}

/**
 * Updates text displayed on the custom glassmorphic trigger.
 */
function updateTriggerText(triggerEl, timeStr) {
  if (!triggerEl) return;
  const valSpan = triggerEl.querySelector('.gt-val');
  if (valSpan) {
    valSpan.textContent = formatDisplayTime(timeStr);
  }
}

/**
 * Enhances a native <input type="time"> into a glassmorphic time picker button.
 */
export function attachGlassTimePicker(inputEl) {
  if (!inputEl || inputEl.dataset.glassEnhanced === '1') return;
  inputEl.dataset.glassEnhanced = '1';

  // Ensure global events are active
  bindGlobalEvents();

  // Create custom glassmorphic trigger button
  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'glass-time-trigger';
  trigger.setAttribute('aria-haspopup', 'dialog');
  trigger.setAttribute('aria-expanded', 'false');
  trigger.setAttribute('aria-label', inputEl.getAttribute('aria-label') || 'Select time');

  if (inputEl.id) {
    trigger.id = `${inputEl.id}-glass-trigger`;
    trigger.dataset.targetId = inputEl.id;
  }

  const initialVal = inputEl.value || '12:00';
  trigger.innerHTML = `
    <span class="gt-val">${formatDisplayTime(initialVal)}</span>
    <span class="gt-icon" aria-hidden="true">🕒</span>
  `;

  // Hide the native input from view and click interception so the clunky native browser popup NEVER appears!
  // Keeping the element in the DOM ensures element IDs, `.value`, and change events remain 100% compatible.
  inputEl.style.display = 'none';

  // Insert trigger right where the input was
  inputEl.parentNode.insertBefore(trigger, inputEl.nextSibling);

  // Wrap the .value setter on the input so programmatically changing input.value immediately updates the trigger
  try {
    const protoDescriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    if (protoDescriptor && protoDescriptor.set) {
      Object.defineProperty(inputEl, 'value', {
        get() {
          return protoDescriptor.get.call(this);
        },
        set(val) {
          protoDescriptor.set.call(this, val);
          updateTriggerText(trigger, val);
        },
        configurable: true,
      });
    }
  } catch (_) {}

  // Update trigger whenever the input fires an input or change event
  inputEl.addEventListener('change', () => {
    updateTriggerText(trigger, inputEl.value);
  });
  inputEl.addEventListener('input', () => {
    updateTriggerText(trigger, inputEl.value);
  });

  // Clicking trigger opens our custom glassmorphic dropdown
  trigger.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    openGlassTimePicker(inputEl, trigger);
  });
}

/**
 * Scans the DOM and enhances all time inputs into glassmorphic time pickers.
 */
export function initGlassTimePickers(root = document) {
  if (!root || typeof root.querySelectorAll !== 'function') return;

  const timeInputs = root.querySelectorAll(
    'input[type="time"], #led-night-start, #led-night-end, #screen-night-start, #screen-night-end, #ai-schedule-start-input, #ai-schedule-end-input'
  );

  timeInputs.forEach((input) => {
    attachGlassTimePicker(input);
  });
}

window.initGlassTimePickers = initGlassTimePickers;
window.attachGlassTimePicker = attachGlassTimePicker;
window.openGlassTimePicker = openGlassTimePicker;
window.closeGlassTimePicker = closeGlassTimePicker;
window.parseTime24 = parseTime24;
window.formatTime24 = formatTime24;
window.formatDisplayTime = formatDisplayTime;
