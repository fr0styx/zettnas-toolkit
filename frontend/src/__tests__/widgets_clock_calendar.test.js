import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  openTimezoneModal,
  closeTimezoneModal,
  setupTimezoneModalEvents,
  openCalendarModal,
  closeCalendarModal,
  setupCalendarModalEvents,
  setupWidgetSettingsEvents,
  applyWidgetConfig,
  loadWidgetConfig,
  saveWidgetConfig,
  renderTimezoneList,
  updateTzModalPreview,
  renderModalCalendarGrid,
  renderCalendar,
  initTimezoneControls,
  initCalendarView,
} from '../components/widgets.js';
import { api } from '../api.js';

describe('Desktop Widgets - Time Clock & Calendar Modal Interactivity', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();

    document.body.innerHTML = `
      <div id="desktop-widgets-container" class="pos-top-right glass-standard scale-normal">
        <!-- 1. Time Clock Widget -->
        <div class="desktop-widget" id="widget-clock" role="button" tabindex="0" title="Click to change timezone & clock format" style="cursor: pointer;">
          <div class="widget-header">
            <span class="widget-title">Time Clock</span>
            <span class="widget-badge" id="w-clock-tz" title="Click to toggle 12h/24h" style="cursor: pointer;">24H</span>
          </div>
          <div>
            <div id="w-clock-time">12:00<span id="w-clock-sec">:00</span></div>
            <span id="w-clock-ampm"></span>
            <div id="w-clock-date">Mon, Oct 19, 2026</div>
          </div>
        </div>

        <!-- 2. Calendar Widget -->
        <div class="desktop-widget" id="widget-calendar" role="button" tabindex="0" title="Click to view notes, reminders & calendar sync" style="display: block; cursor: pointer;">
          <div class="widget-header">
            <span class="widget-title">Calendar <span class="widget-badge" id="w-cal-country-badge">US</span></span>
            <div>
              <button id="w-cal-prev">◀</button>
              <span class="widget-badge" id="w-cal-month">OCT 2026</span>
              <button id="w-cal-next">▶</button>
            </div>
          </div>
          <div id="w-calendar-grid" class="widget-calendar-grid">
            <div class="cal-day" data-day="19">19</div>
          </div>
          <div id="w-cal-glance-bar" class="cal-glance-bar" data-date-key="2026-10-12">
            <span>Oct 12: Columbus Day</span>
          </div>
        </div>
      </div>

      <!-- Timezone Modal -->
      <div id="modal-clock-timezone" class="smart-modal-backdrop" role="dialog" aria-modal="true" style="display: none;">
        <div class="smart-modal-window">
          <div class="smart-modal-header">
            <span class="smart-modal-title">Timezone & Clock Settings</span>
            <button class="win-btn close-btn" id="modal-clock-tz-close-btn" title="Close"></button>
          </div>
          <div class="smart-modal-body">
            <div id="modal-tz-preview-time">--:--</div>
            <div id="modal-tz-preview-sec">:--</div>
            <div id="modal-tz-preview-ampm"></div>
            <div id="modal-tz-preview-date">--</div>
            <div id="modal-tz-active-pill">Local Time (Auto)</div>
            <button type="button" id="btn-tz-fmt-12">12H</button>
            <button type="button" id="btn-tz-fmt-24">24H</button>
            <button type="button" id="btn-tz-use-browser">Use Local</button>
            <input type="text" id="tz-search-input" />
            <div id="tz-region-pills">
              <button type="button" class="tz-region-pill active" data-region="all">All</button>
              <button type="button" class="tz-region-pill" data-region="Americas">Americas</button>
            </div>
            <div id="tz-items-list"></div>
            <input type="text" id="tz-custom-input" />
            <button type="button" id="btn-tz-apply-custom">Apply</button>
            <button type="button" id="modal-clock-tz-cancel-btn">Cancel</button>
            <button type="button" id="modal-clock-tz-save-btn">Apply & Save</button>
          </div>
        </div>
      </div>

      <!-- Calendar Modal -->
      <div id="modal-calendar-notes" class="smart-modal-backdrop" role="dialog" aria-modal="true" style="display: none;">
        <div class="smart-modal-window">
          <div class="smart-modal-header">
            <span class="smart-modal-title">Calendar & Day Reminders</span>
            <button class="win-btn close-btn" id="modal-cal-notes-close-btn" title="Close"></button>
          </div>
          <div class="smart-modal-body">
            <span id="modal-cal-month-title">October 2026</span>
            <button id="btn-modal-cal-prev">Prev</button>
            <button id="btn-modal-cal-next">Next</button>
            <button id="btn-modal-cal-today">Today</button>
            <div id="modal-cal-grid"></div>
            <div id="modal-cal-selected-date-str"></div>
            <div id="modal-cal-selected-sub"></div>
            <div id="modal-cal-agenda-list"></div>
            <input type="text" id="cal-new-note-title" />
            <input type="time" id="cal-new-note-time" />
            <select id="cal-new-note-type"><option value="note">Note</option></select>
            <button type="button" id="btn-cal-save-note">Add</button>
            <div id="cal-feeds-list"></div>
          </div>
        </div>
      </div>
    `;

    loadWidgetConfig();
    saveWidgetConfig({
      widgets: { clock: true, calendar: true },
    });
    applyWidgetConfig();
    setupWidgetSettingsEvents();
    setupTimezoneModalEvents();
    setupCalendarModalEvents();

    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/api/calendar/events')) return { events: [] };
      if (url.includes('/api/calendar/feeds')) return { feeds: [] };
      return {};
    });
  });

  describe('Time Clock Widget & Timezone Modal', () => {
    it('opens timezone modal with .open class and display:flex when openTimezoneModal() is called', () => {
      const modal = document.getElementById('modal-clock-timezone');
      expect(modal.classList.contains('open')).toBe(false);
      expect(modal.style.display).toBe('none');

      openTimezoneModal();

      expect(modal.classList.contains('open')).toBe(true);
      expect(modal.style.display).toBe('flex');
    });

    it('removes .open class and sets display:none when closeTimezoneModal() is called', () => {
      const modal = document.getElementById('modal-clock-timezone');
      openTimezoneModal();
      expect(modal.classList.contains('open')).toBe(true);

      closeTimezoneModal();
      expect(modal.classList.contains('open')).toBe(false);
      expect(modal.style.display).toBe('none');
    });

    it('opens modal when clicking on the #widget-clock container', () => {
      const wClock = document.getElementById('widget-clock');
      const modal = document.getElementById('modal-clock-timezone');

      wClock.click();

      expect(modal.classList.contains('open')).toBe(true);
      expect(modal.style.display).toBe('flex');
    });

    it('opens modal when clicking child elements of #widget-clock (time text)', () => {
      const timeEl = document.getElementById('w-clock-time');
      const modal = document.getElementById('modal-clock-timezone');

      timeEl.click();

      expect(modal.classList.contains('open')).toBe(true);
      expect(modal.style.display).toBe('flex');
    });

    it('closes modal when clicking the close button (#modal-clock-tz-close-btn)', () => {
      const modal = document.getElementById('modal-clock-timezone');
      const closeBtn = document.getElementById('modal-clock-tz-close-btn');

      openTimezoneModal();
      expect(modal.classList.contains('open')).toBe(true);

      closeBtn.click();
      expect(modal.classList.contains('open')).toBe(false);
      expect(modal.style.display).toBe('none');
    });

    it('closes modal when clicking the cancel button (#modal-clock-tz-cancel-btn)', () => {
      const modal = document.getElementById('modal-clock-timezone');
      const cancelBtn = document.getElementById('modal-clock-tz-cancel-btn');

      openTimezoneModal();
      cancelBtn.click();

      expect(modal.classList.contains('open')).toBe(false);
      expect(modal.style.display).toBe('none');
    });

    it('closes modal when clicking directly on the backdrop overlay', () => {
      const modal = document.getElementById('modal-clock-timezone');
      openTimezoneModal();

      modal.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(modal.classList.contains('open')).toBe(false);
      expect(modal.style.display).toBe('none');
    });

    it('closes modal when pressing the Escape key', () => {
      const modal = document.getElementById('modal-clock-timezone');
      openTimezoneModal();
      expect(modal.classList.contains('open')).toBe(true);

      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));

      expect(modal.classList.contains('open')).toBe(false);
      expect(modal.style.display).toBe('none');
    });

    it('toggles 12H/24H format on #w-clock-tz badge click with stopPropagation without opening modal', () => {
      const tzBadge = document.getElementById('w-clock-tz');
      const modal = document.getElementById('modal-clock-timezone');

      tzBadge.click();

      // Badge toggles format, should NOT open the timezone modal
      expect(modal.classList.contains('open')).toBe(false);
      expect(modal.style.display).toBe('none');
    });
  });

  describe('Calendar Widget & Calendar Notes Modal', () => {
    it('opens calendar modal with .open class and display:flex when openCalendarModal() is called', () => {
      const modal = document.getElementById('modal-calendar-notes');
      expect(modal.classList.contains('open')).toBe(false);
      expect(modal.style.display).toBe('none');

      openCalendarModal();

      expect(modal.classList.contains('open')).toBe(true);
      expect(modal.style.display).toBe('flex');
    });

    it('removes .open class and sets display:none when closeCalendarModal() is called', () => {
      const modal = document.getElementById('modal-calendar-notes');
      openCalendarModal();
      expect(modal.classList.contains('open')).toBe(true);

      closeCalendarModal();
      expect(modal.classList.contains('open')).toBe(false);
      expect(modal.style.display).toBe('none');
    });

    it('opens modal when clicking on a calendar day cell (.cal-day)', () => {
      const dayCell = document.querySelector('.cal-day');
      const modal = document.getElementById('modal-calendar-notes');

      dayCell.click();

      expect(modal.classList.contains('open')).toBe(true);
      expect(modal.style.display).toBe('flex');
    });

    it('opens modal when clicking on the holiday glance bar (#w-cal-glance-bar)', () => {
      const glanceBar = document.getElementById('w-cal-glance-bar');
      const modal = document.getElementById('modal-calendar-notes');

      glanceBar.click();

      expect(modal.classList.contains('open')).toBe(true);
      expect(modal.style.display).toBe('flex');
    });

    it('opens modal when clicking anywhere else on the calendar widget', () => {
      const wCalendar = document.getElementById('widget-calendar');
      const modal = document.getElementById('modal-calendar-notes');

      wCalendar.click();

      expect(modal.classList.contains('open')).toBe(true);
      expect(modal.style.display).toBe('flex');
    });

    it('does not open modal when navigating months with prev/next buttons', () => {
      const prevBtn = document.getElementById('w-cal-prev');
      const nextBtn = document.getElementById('w-cal-next');
      const modal = document.getElementById('modal-calendar-notes');

      prevBtn.click();
      expect(modal.classList.contains('open')).toBe(false);

      nextBtn.click();
      expect(modal.classList.contains('open')).toBe(false);
    });

    it('closes modal when clicking the close button (#modal-cal-notes-close-btn)', () => {
      const modal = document.getElementById('modal-calendar-notes');
      const closeBtn = document.getElementById('modal-cal-notes-close-btn');

      openCalendarModal();
      expect(modal.classList.contains('open')).toBe(true);

      closeBtn.click();
      expect(modal.classList.contains('open')).toBe(false);
      expect(modal.style.display).toBe('none');
    });

    it('closes modal when clicking directly on the backdrop overlay', () => {
      const modal = document.getElementById('modal-calendar-notes');
      openCalendarModal();

      modal.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(modal.classList.contains('open')).toBe(false);
      expect(modal.style.display).toBe('none');
    });

    it('closes modal when pressing the Escape key', () => {
      const modal = document.getElementById('modal-calendar-notes');
      openCalendarModal();
      expect(modal.classList.contains('open')).toBe(true);

      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));

      expect(modal.classList.contains('open')).toBe(false);
      expect(modal.style.display).toBe('none');
    });
  });

  describe('Mission Control In-Flow Routing & Controls Initialization', () => {
    it('calls window.openManagementWindow with correct section and subtab when openTimezoneModal is invoked', () => {
      const openMgmtSpy = vi.fn();
      window.openManagementWindow = openMgmtSpy;

      openTimezoneModal();

      expect(openMgmtSpy).toHaveBeenCalledWith('mgmt-sec-wallpaper', 'mgmt-pane-language');
    });

    it('calls window.openManagementWindow with calendar section and subtab when openCalendarModal is invoked', () => {
      const openMgmtSpy = vi.fn();
      window.openManagementWindow = openMgmtSpy;

      openCalendarModal('2026-10-19');

      expect(openMgmtSpy).toHaveBeenCalledWith('mgmt-sec-wallpaper', 'mgmt-pane-calendar');
    });

    it('initializes timezone list and clock preview with initTimezoneControls without crashing', () => {
      expect(() => initTimezoneControls()).not.toThrow();

      const timeEl = document.getElementById('modal-tz-preview-time');
      expect(timeEl.textContent).not.toBe('--:--');
      expect(timeEl.textContent).toMatch(/\d{1,2}:\d{2}/);

      const tzList = document.getElementById('tz-items-list');
      expect(tzList.children.length).toBeGreaterThan(0);
    });

    it('initializes calendar grid and day agenda with initCalendarView', () => {
      expect(() => initCalendarView('2026-10-19')).not.toThrow();

      const grid = document.getElementById('modal-cal-grid');
      expect(grid.children.length).toBeGreaterThan(0);

      const title = document.getElementById('modal-cal-selected-date-str');
      expect(title.textContent).toContain('2026');
    });
  });
});

