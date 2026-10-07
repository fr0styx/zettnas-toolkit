import { describe, it, expect, beforeEach, vi } from 'vitest';
import { makeDraggable, saveWindowBounds, loadSavedWindowBounds, DockManager, isEventChecked, markEventChecked, getEventKey, openConsoleWindow, KNOWN_APPS } from '../components/dock.js';
import { openEventDetailModal, closeEventDetailModal } from '../modals.js';

describe('Notification Center Draggable Window & Event Detail Inspector', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="os-dock-container">
        <div id="os-dock"></div>
      </div>
      <div id="global-toast-container"></div>
      <div id="notif-center-panel" class="notif-center-window" style="position:fixed; width:360px; height:420px; display:none;">
        <div id="notif-center-header" style="cursor:move;">
          <div class="os-window-controls">
            <button class="win-btn close-btn" id="notif-close-btn" title="Close"></button>
          </div>
          <span class="title">Notification Center</span>
          <button id="notif-mark-read">Mark all read</button>
          <button id="notif-clear-all">Clear all</button>
        </div>
        <div id="notif-filter-bar">
          <button class="notif-filter-btn active" data-filter="all">All</button>
          <button class="notif-filter-btn" data-filter="error">Errors</button>
        </div>
        <div id="notif-center-list"></div>
      </div>

      <div id="event-detail-modal-overlay" class="smart-modal-backdrop" style="display:none;">
        <div class="smart-modal-window event-detail-window">
          <div class="smart-modal-header" id="event-detail-header">
            <span class="smart-modal-title" id="event-detail-title">
              <span id="event-detail-header-icon">ℹ️</span>
              <span>Event Details</span>
            </span>
            <div class="os-window-controls">
              <button class="win-btn close-btn" id="event-detail-close"></button>
            </div>
          </div>
          <div class="smart-modal-body">
            <span id="event-detail-badge">
              <span id="event-detail-badge-icon">ℹ️</span>
              <span id="event-detail-badge-text">INFO</span>
            </span>
            <span id="event-detail-subsystem">SYSTEM</span>
            <div id="event-detail-reltime">--</div>
            <div id="event-detail-event-title"></div>
            <div id="event-detail-event-message"></div>
            <div id="event-detail-localtime">--</div>
            <div id="event-detail-epoch">--</div>
            <button id="event-detail-copy-btn">
              <span id="event-detail-copy-icon">📋</span>
              <span id="event-detail-copy-text">Copy Details</span>
            </button>
            <pre id="event-detail-raw"></pre>
            <button id="event-detail-context-btn" style="display:none;"></button>
            <button id="event-detail-close-btn">Close</button>
          </div>
        </div>
      </div>
    `;
  });

  it('makes Notification Center draggable and saves/applies window bounds', () => {
    const panel = document.getElementById('notif-center-panel');
    const header = document.getElementById('notif-center-header');

    saveWindowBounds('notif-center', { left: 450, top: 220, width: 380, height: 460 });
    const bounds = loadSavedWindowBounds();
    expect(bounds['notif-center']).toBeDefined();
    expect(bounds['notif-center'].left).toBe(450);
    expect(bounds['notif-center'].top).toBe(220);

    makeDraggable(panel, header, 'notif-center');
    expect(panel.style.left).toBe('450px');
    expect(panel.style.top).toBe('220px');
  });

  it('populates and opens Event Detail Modal for a thermal/fan warning event', () => {
    const mockEvent = {
      ts: 1791393000,
      level: 'warning',
      title: 'CPU Fan Speed High',
      message: 'PWM duty reached 85% at 68°C',
      details: { fan_idx: 1, rpm: 2250, target_rpm: 2300 }
    };

    openEventDetailModal(mockEvent);

    const overlay = document.getElementById('event-detail-modal-overlay');
    expect(overlay.classList.contains('open')).toBe(true);
    expect(overlay.style.display).toBe('flex');

    const badgeText = document.getElementById('event-detail-badge-text');
    expect(badgeText.textContent).toBe('WARNING');

    const subsystem = document.getElementById('event-detail-subsystem');
    expect(subsystem.textContent).toBe('THERMAL & FANS');

    const title = document.getElementById('event-detail-event-title');
    expect(title.textContent).toBe('CPU Fan Speed High');

    const message = document.getElementById('event-detail-event-message');
    expect(message.textContent).toBe('PWM duty reached 85% at 68°C');

    const raw = document.getElementById('event-detail-raw');
    expect(raw.textContent).toContain('"fan_idx": 1');

    const contextBtn = document.getElementById('event-detail-context-btn');
    expect(contextBtn.style.display).toBe('inline-block');
    expect(contextBtn.textContent).toBe('Open Fan Control');
  });

  it('populates and opens Event Detail Modal for a SMART disk error event', () => {
    const mockEvent = {
      ts: 1791393100,
      level: 'error',
      title: 'Drive Health Degradation Alert',
      message: 'Uncorrectable pending sectors detected on sda',
      details: { dev: 'sda', pending_sectors: 16 }
    };

    openEventDetailModal(mockEvent);

    const overlay = document.getElementById('event-detail-modal-overlay');
    expect(overlay.classList.contains('open')).toBe(true);

    const badgeText = document.getElementById('event-detail-badge-text');
    expect(badgeText.textContent).toBe('ERROR');

    const subsystem = document.getElementById('event-detail-subsystem');
    expect(subsystem.textContent).toBe('STORAGE & S.M.A.R.T.');

    const contextBtn = document.getElementById('event-detail-context-btn');
    expect(contextBtn.style.display).toBe('inline-block');
    expect(contextBtn.textContent).toBe('Inspect S.M.A.R.T.');
  });

  it('closes Event Detail Modal properly', () => {
    const mockEvent = {
      ts: 1791393200,
      level: 'info',
      title: 'Docker Telemetry Started',
      message: 'Monitoring 12 container instances'
    };

    openEventDetailModal(mockEvent);
    const overlay = document.getElementById('event-detail-modal-overlay');
    expect(overlay.style.display).toBe('flex');

    closeEventDetailModal();
    expect(overlay.classList.contains('open')).toBe(false);
    expect(overlay.style.display).toBe('none');
  });

  it('correctly tracks and checks notification events with dimming state', () => {
    const event1 = { ts: 1791394000, level: 'warning', title: 'NVMe Temperature High', message: 'nvme0 reached 72C' };
    const event2 = { ts: 1791394050, level: 'info', title: 'ZFS Scrub Completed', message: 'Pool storage scrub finished' };

    expect(isEventChecked(event1)).toBe(false);
    expect(isEventChecked(event2)).toBe(false);

    markEventChecked(event1);

    expect(isEventChecked(event1)).toBe(true);
    expect(isEventChecked(event2)).toBe(false);

    const savedRaw = localStorage.getItem('zettnas_checked_events_v1');
    expect(savedRaw).toBeDefined();
    expect(savedRaw).toContain('NVMe Temperature High');
  });

  it('renders only 2 icons on clean initial dock startup: Dashboard Home and Notification Center', () => {
    DockManager.windows = {};
    DockManager.activeId = null;
    DockManager.render();

    const dock = document.getElementById('os-dock');
    const items = dock.querySelectorAll('.dock-item');
    expect(items.length).toBe(2);

    // First item is Dashboard Home
    expect(items[0].getAttribute('aria-label')).toBe('Dashboard Home');
    expect(items[0].innerHTML).toContain('#i-globe');

    // Second item is Notification Center
    expect(items[1].getAttribute('aria-label')).toBe('Notification Center');
    expect(items[1].innerHTML).toContain('#i-bell');
  });

  it('allows user to pin and unpin apps in the dock bar', () => {
    DockManager.windows = {};
    DockManager.activeId = null;

    expect(DockManager.isPinned('fm')).toBe(false);

    // Pin File Explorer
    DockManager.pinApp('fm');
    expect(DockManager.isPinned('fm')).toBe(true);
    expect(DockManager.getPinnedApps()).toContain('fm');

    // Dock now has 3 items: Home, File Explorer, Notification Center
    const dock = document.getElementById('os-dock');
    let items = dock.querySelectorAll('.dock-item');
    expect(items.length).toBe(3);

    const fmItem = dock.querySelector('[data-window-id="fm"]');
    expect(fmItem).not.toBeNull();
    expect(fmItem.classList.contains('pinned-closed')).toBe(true);

    // When File Explorer is opened/registered
    const mockFmEl = document.createElement('div');
    DockManager.register('fm', mockFmEl, '#i-storage', 'File Explorer', false);
    items = dock.querySelectorAll('.dock-item');
    expect(items.length).toBe(3);
    const runningFmItem = dock.querySelector('[data-window-id="fm"]');
    expect(runningFmItem.classList.contains('pinned-closed')).toBe(false);

    // When closed/unregistered, pinned app remains in dock as pinned-closed
    DockManager.unregister('fm');
    items = dock.querySelectorAll('.dock-item');
    expect(items.length).toBe(3);
    expect(dock.querySelector('[data-window-id="fm"]').classList.contains('pinned-closed')).toBe(true);

    // Unpin File Explorer
    DockManager.unpinApp('fm');
    expect(DockManager.isPinned('fm')).toBe(false);
    expect(DockManager.getPinnedApps()).not.toContain('fm');

    // Dock returns to exactly 2 items
    items = dock.querySelectorAll('.dock-item');
    expect(items.length).toBe(2);
  });

  it('opens and visibly restores ZettNAS console window when openConsoleWindow() is triggered', () => {
    DockManager.windows = {};
    DockManager.activeId = null;

    const overlay = document.createElement('div');
    overlay.id = 'console-modal-overlay';
    overlay.className = 'smart-modal-backdrop window-minimized';
    overlay.style.display = 'none';

    const win = document.createElement('div');
    win.id = 'console-window';
    win.className = 'chassis-front-panel window-minimized';
    overlay.appendChild(win);
    document.body.appendChild(overlay);

    openConsoleWindow();

    expect(overlay.classList.contains('open')).toBe(true);
    expect(overlay.classList.contains('window-minimized')).toBe(false);
    expect(overlay.style.display).not.toBe('none');

    expect(win.classList.contains('window-minimized')).toBe(false);
    expect(win.style.display).not.toBe('none');

    expect(DockManager.windows['console']).toBeDefined();
    expect(DockManager.windows['console'].minimized).toBe(false);
    expect(DockManager.windows['console'].closed).toBe(false);

    // Verify dock has console item running
    const dock = document.getElementById('os-dock');
    const consoleDockItem = dock.querySelector('[data-window-id="console"]');
    expect(consoleDockItem).not.toBeNull();
    expect(consoleDockItem.classList.contains('pinned-closed')).toBe(false);

    // Verify closing console hides window and unregisters if unpinned
    DockManager.closeWindow('console');
    expect(overlay.classList.contains('open')).toBe(false);
    expect(win.classList.contains('window-minimized')).toBe(true);
    expect(DockManager.windows['console']).toBeUndefined();
    expect(dock.querySelector('[data-window-id="console"]')).toBeNull();

    // Now test if pinned:
    DockManager.pinApp('console');
    expect(DockManager.isPinned('console')).toBe(true);
    expect(dock.querySelector('[data-window-id="console"]').classList.contains('pinned-closed')).toBe(true);

    // Reopen console via KNOWN_APPS.console.launch()
    KNOWN_APPS.console.launch();
    expect(overlay.classList.contains('open')).toBe(true);
    expect(win.classList.contains('window-minimized')).toBe(false);
    expect(dock.querySelector('[data-window-id="console"]').classList.contains('pinned-closed')).toBe(false);
  });
});
