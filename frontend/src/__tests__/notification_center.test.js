import { describe, it, expect, beforeEach, vi } from 'vitest';
import { makeDraggable, makeResizable, saveWindowBounds, loadSavedWindowBounds, DockManager, isEventChecked, markEventChecked, resetCheckedEventsState, getEventKey, openConsoleWindow, KNOWN_APPS, toggleConsoleMaximize, renderNotificationCenter, saveOpenWindowsState, restoreOpenWindowsState, applySavedBounds, OPEN_WINDOWS_KEY } from '../components/dock.js';
import { openEventDetailModal, closeEventDetailModal } from '../modals.js';
import { initManagement } from '../components/management.js';
import { state } from '../state.js';

describe('Notification Center Draggable Window & Event Detail Inspector', () => {
  beforeEach(() => {
    localStorage.clear();
    resetCheckedEventsState();
    document.body.innerHTML = `
      <div id="os-dock-container">
        <div id="os-dock"></div>
      </div>
      <div id="global-toast-container"></div>
      <div id="notif-center-panel" class="notif-center-window" style="position:fixed; width:360px; height:420px; display:none;">
        <div id="notif-center-header" style="cursor:move; display:flex; justify-content:space-between; align-items:center;">
          <div style="display:flex; align-items:center; gap:8px;">
            <span class="title">Notification Center</span>
          </div>
          <div style="display:flex; gap:10px; align-items:center;">
            <button id="notif-mark-read">Mark all read</button>
            <button id="notif-clear-all">Clear all</button>
            <div class="os-window-controls">
              <button class="win-btn close-btn" id="notif-close-btn" title="Close"></button>
            </div>
          </div>
        </div>
        <div id="notif-filter-bar">
          <button class="notif-filter-btn active" data-filter="all">All</button>
          <button class="notif-filter-btn" data-filter="error">Errors</button>
        </div>
        <div id="notif-center-list"></div>
        <div id="notif-center-resizer" class="window-resizer-grip"></div>
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

  it('makes Notification Center resizable via dedicated resizer grip and saves expanded dimensions', () => {
    const panel = document.getElementById('notif-center-panel');
    const resizer = document.getElementById('notif-center-resizer');

    window.innerWidth = 1200;
    window.innerHeight = 1000;

    panel.getBoundingClientRect = () => ({
      left: 100,
      top: 100,
      width: 380,
      height: 480,
      right: 480,
      bottom: 580
    });

    makeResizable(panel, resizer, 'notif-center', { minWidth: 320, minHeight: 240 });

    // Simulate pointerdown on resizer
    const pDown = new MouseEvent('pointerdown', { clientX: 480, clientY: 580, button: 0, bubbles: true });
    resizer.dispatchEvent(pDown);

    // Simulate pointermove to expand window
    const pMove = new MouseEvent('pointermove', { clientX: 600, clientY: 750, bubbles: true });
    window.dispatchEvent(pMove);

    expect(parseInt(panel.style.width, 10)).toBe(500); // 380 + (600 - 480) = 500
    expect(parseInt(panel.style.height, 10)).toBe(650); // 480 + (750 - 580) = 650

    // Simulate pointerup to persist
    panel.getBoundingClientRect = () => ({
      left: 100,
      top: 100,
      width: 500,
      height: 650,
      right: 600,
      bottom: 750
    });
    const pUp = new MouseEvent('pointerup', { clientX: 600, clientY: 750, bubbles: true });
    window.dispatchEvent(pUp);

    const bounds = loadSavedWindowBounds();
    expect(bounds['notif-center']).toBeDefined();
    expect(bounds['notif-center'].width).toBe(500);
    expect(bounds['notif-center'].height).toBe(650);
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

  it('checking an individual event marks ONLY that specific event as checked and does not dim older events below it', () => {
    resetCheckedEventsState();

    // 4 events sorted newest to oldest (event1 is newest, event4 is oldest)
    const event1 = { ts: 1791394300, level: 'info', title: 'Backup Finished', message: 'Backup job done' };
    const event2 = { ts: 1791394200, level: 'error', title: 'CPU Thermal Critical', message: 'Core temp exceeded 90C' };
    const event3 = { ts: 1791394100, level: 'warning', title: 'Disk Pool Warning', message: 'Disk space above 85%' };
    const event4 = { ts: 1791394000, level: 'info', title: 'Network Link Up', message: 'eth0 negotiated 10Gbps' };

    // Initially all are unread
    expect(isEventChecked(event1)).toBe(false);
    expect(isEventChecked(event2)).toBe(false);
    expect(isEventChecked(event3)).toBe(false);
    expect(isEventChecked(event4)).toBe(false);

    // User clicks/checks specifically event2
    markEventChecked(event2);

    // ONLY event2 should be checked. Older events (event3, event4) MUST NOT be checked!
    expect(isEventChecked(event1)).toBe(false);
    expect(isEventChecked(event2)).toBe(true);
    expect(isEventChecked(event3)).toBe(false);
    expect(isEventChecked(event4)).toBe(false);

    // Now test DOM rendering in Notification Center
    state.latestStats = {
      events: [event1, event2, event3, event4]
    };
    const list = document.getElementById('notif-center-list');
    list._lastRenderedSignature = null;
    renderNotificationCenter();

    const items = list.querySelectorAll('.notif-center-item');
    expect(items.length).toBe(4);

    // Item 1 (event1): not dimmed, has unread dot
    expect(items[0].classList.contains('notif-event-checked')).toBe(false);
    expect(items[0].querySelector('.notif-unread-dot')).not.toBeNull();

    // Item 2 (event2): dimmed, no unread dot
    expect(items[1].classList.contains('notif-event-checked')).toBe(true);
    expect(items[1].querySelector('.notif-unread-dot')).toBeNull();

    // Item 3 (event3 - chronologically older and below event2): MUST NOT be dimmed, MUST have unread dot
    expect(items[2].classList.contains('notif-event-checked')).toBe(false);
    expect(items[2].querySelector('.notif-unread-dot')).not.toBeNull();

    // Item 4 (event4 - chronologically older and below event3): MUST NOT be dimmed, MUST have unread dot
    expect(items[3].classList.contains('notif-event-checked')).toBe(false);
    expect(items[3].querySelector('.notif-unread-dot')).not.toBeNull();
  });

  it('renders default icons on clean initial dock startup: Dashboard Home, Spotlight, Notification Center, and User Profile', () => {
    DockManager.windows = {};
    DockManager.activeId = null;
    DockManager.render();

    const dock = document.getElementById('os-dock');
    const items = dock.querySelectorAll('.dock-item');
    expect(items.length).toBe(4);

    // First item is Dashboard Home
    expect(items[0].getAttribute('aria-label')).toBe('Dashboard Home');
    expect(items[0].innerHTML).toContain('#i-globe');

    // Second item is Spotlight
    expect(items[1].getAttribute('aria-label')).toContain('Spotlight');

    // Third item is Notification Center
    expect(items[2].getAttribute('aria-label')).toBe('Notification Center');
    expect(items[2].innerHTML).toContain('#i-bell');

    // Fourth item is User Profile
    expect(items[3].getAttribute('aria-label')).toBe('User Profile & Identity');
  });

  it('allows user to pin and unpin apps in the dock bar', () => {
    DockManager.windows = {};
    DockManager.activeId = null;

    expect(DockManager.isPinned('fm')).toBe(false);

    // Pin File Explorer
    DockManager.pinApp('fm');
    expect(DockManager.isPinned('fm')).toBe(true);
    expect(DockManager.getPinnedApps()).toContain('fm');

    // Dock now has 5 items: Home, Spotlight, File Explorer, Notification Center, User Profile
    const dock = document.getElementById('os-dock');
    let items = dock.querySelectorAll('.dock-item');
    expect(items.length).toBe(5);

    const fmItem = dock.querySelector('[data-window-id="fm"]');
    expect(fmItem).not.toBeNull();
    expect(fmItem.classList.contains('pinned-closed')).toBe(true);

    // When File Explorer is opened/registered
    const mockFmEl = document.createElement('div');
    DockManager.register('fm', mockFmEl, '#i-storage', 'File Explorer', false);
    items = dock.querySelectorAll('.dock-item');
    expect(items.length).toBe(5);
    const runningFmItem = dock.querySelector('[data-window-id="fm"]');
    expect(runningFmItem.classList.contains('pinned-closed')).toBe(false);

    // When closed/unregistered, pinned app remains in dock as pinned-closed
    DockManager.unregister('fm');
    items = dock.querySelectorAll('.dock-item');
    expect(items.length).toBe(5);
    expect(dock.querySelector('[data-window-id="fm"]').classList.contains('pinned-closed')).toBe(true);

    // Unpin File Explorer
    DockManager.unpinApp('fm');
    expect(DockManager.isPinned('fm')).toBe(false);
    expect(DockManager.getPinnedApps()).not.toContain('fm');

    // Dock returns to 4 default items
    items = dock.querySelectorAll('.dock-item');
    expect(items.length).toBe(4);
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

  it('action button in Event Detail Modal triggers openDrawer for thermal events and closes modal', () => {
    window.openDrawer = vi.fn();
    const mockEvent = {
      ts: 1791393000,
      level: 'warning',
      title: 'CPU Fan Speed High',
      message: 'PWM duty reached 85% at 68°C',
      details: { fan_idx: 1, rpm: 2250 }
    };

    openEventDetailModal(mockEvent);
    const overlay = document.getElementById('event-detail-modal-overlay');
    expect(overlay.classList.contains('open')).toBe(true);

    const contextBtn = document.getElementById('event-detail-context-btn');
    expect(contextBtn.style.display).toBe('inline-block');
    expect(contextBtn.textContent).toBe('Open Fan Control');

    contextBtn.click();
    expect(window.openDrawer).toHaveBeenCalledWith('tab-fans');
    expect(overlay.classList.contains('open')).toBe(false);
  });

  it('action button in Event Detail Modal triggers openManagementWindow for container events', () => {
    window.openManagementWindow = vi.fn();
    const mockEvent = {
      ts: 1791393200,
      level: 'info',
      title: 'Docker Container Alert',
      message: 'Container plex high memory usage',
      details: { container: 'plex' }
    };

    openEventDetailModal(mockEvent);
    const overlay = document.getElementById('event-detail-modal-overlay');
    expect(overlay.classList.contains('open')).toBe(true);

    const contextBtn = document.getElementById('event-detail-context-btn');
    expect(contextBtn.textContent).toBe('Open Container Telemetry');

    contextBtn.click();
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-pane-docker');
    expect(overlay.classList.contains('open')).toBe(false);
  });

  it('action button in Event Detail Modal triggers openDrawer for SD Card events and sets MEDIA & INGEST subsystem', () => {
    window.openDrawer = vi.fn();
    const mockEvent = {
      ts: 1791409981,
      level: 'info',
      title: 'SD Card Ejected',
      message: 'SD Card was safely unmounted and ejected. You can now physically remove it.'
    };

    openEventDetailModal(mockEvent);
    const overlay = document.getElementById('event-detail-modal-overlay');
    expect(overlay.classList.contains('open')).toBe(true);

    const subsystemEl = document.getElementById('event-detail-subsystem');
    expect(subsystemEl.textContent).toBe('MEDIA & INGEST');

    const contextBtn = document.getElementById('event-detail-context-btn');
    expect(contextBtn.textContent).toBe('Open Media Card Settings');

    contextBtn.click();
    expect(window.openDrawer).toHaveBeenCalledWith('tab-buttons');
    expect(overlay.classList.contains('open')).toBe(false);
  });

  it('action button in Event Detail Modal triggers openDrawer for LED events', () => {
    window.openDrawer = vi.fn();
    const mockEvent = {
      ts: 1791409990,
      level: 'info',
      title: 'LED Mode Changed',
      message: 'Applied Cyber Cyan ARGB lightbar profile'
    };

    openEventDetailModal(mockEvent);
    const subsystemEl = document.getElementById('event-detail-subsystem');
    expect(subsystemEl.textContent).toBe('ARGB LIGHTBAR');

    const contextBtn = document.getElementById('event-detail-context-btn');
    expect(contextBtn.textContent).toBe('Open LED Controls');

    contextBtn.click();
    expect(window.openDrawer).toHaveBeenCalledWith('tab-led');
  });

  it('action button in Event Detail Modal triggers openManagementWindow for Security events', () => {
    window.openManagementWindow = vi.fn();
    const mockEvent = {
      ts: 1791410000,
      level: 'success',
      title: 'Security',
      message: 'Generated new API token: Grafana'
    };

    openEventDetailModal(mockEvent);
    const subsystemEl = document.getElementById('event-detail-subsystem');
    expect(subsystemEl.textContent).toBe('SECURITY & ACCESS');

    const contextBtn = document.getElementById('event-detail-context-btn');
    expect(contextBtn.textContent).toBe('Open Security Settings');

    contextBtn.click();
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-pane-security');
  });

  it('action button in Event Detail Modal triggers openManagementWindow for UPS events', () => {
    window.openManagementWindow = vi.fn();
    const mockEvent = {
      ts: 1791410010,
      level: 'warning',
      title: 'UPS On Battery',
      message: 'Mains power disconnected. Estimated runtime: 18 min.'
    };

    openEventDetailModal(mockEvent);
    const subsystemEl = document.getElementById('event-detail-subsystem');
    expect(subsystemEl.textContent).toBe('POWER & UPS');

    const contextBtn = document.getElementById('event-detail-context-btn');
    expect(contextBtn.textContent).toBe('Open Power & UPS');

    contextBtn.click();
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-ups');
  });

  it('toggles console window maximize and restore with proportional scaling transform and restores previous position', () => {
    const consoleOverlay = document.createElement('div');
    consoleOverlay.id = 'console-modal-overlay';
    const consoleWin = document.createElement('div');
    consoleWin.id = 'console-window';
    consoleWin.style.position = 'fixed';
    consoleWin.style.left = '120px';
    consoleWin.style.top = '80px';
    const consoleMax = document.createElement('button');
    consoleMax.id = 'console-max';
    consoleMax.setAttribute('title', 'Maximize');

    document.body.appendChild(consoleOverlay);
    document.body.appendChild(consoleWin);
    document.body.appendChild(consoleMax);

    // Maximize
    toggleConsoleMaximize();
    expect(consoleWin.dataset.maximized).toBe('true');
    expect(consoleMax.getAttribute('title')).toBe('Restore');
    expect(consoleWin.style.left).toBe('50%');
    expect(consoleWin.style.transform).toContain('scale(');

    // Restore
    toggleConsoleMaximize();
    expect(consoleWin.dataset.maximized).toBeUndefined();
    expect(consoleMax.getAttribute('title')).toBe('Maximize');
    expect(consoleWin.style.left).toBe('120px');
    expect(consoleWin.style.top).toBe('80px');

    consoleOverlay.remove();
    consoleWin.remove();
    consoleMax.remove();
  });

  it('verifies console popout standalone button is absent from chassis header', () => {
    expect(document.getElementById('console-popout')).toBeNull();
  });

  it('places Notification Center red close button on the right side of the header', () => {
    const header = document.getElementById('notif-center-header');
    const closeBtn = document.getElementById('notif-close-btn');
    const clearAll = document.getElementById('notif-clear-all');
    expect(closeBtn).not.toBeNull();
    expect(clearAll).not.toBeNull();

    // Verify closeBtn follows clearAll in DOM order (on the right)
    expect(clearAll.compareDocumentPosition(closeBtn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('memoizes notification center render to prevent re-render thrashing and blinking', () => {
    state.latestStats = {
      events: [
        { ts: 1791395000, level: 'warning', title: 'Fan Alert', message: 'Fan 1 duty 90%' },
        { ts: 1791394900, level: 'info', title: 'System Boot', message: 'All services up' }
      ]
    };

    const list = document.getElementById('notif-center-list');
    list._lastRenderedSignature = null;
    renderNotificationCenter();

    const itemsInitial = list.querySelectorAll('.notif-center-item');
    expect(itemsInitial.length).toBe(2);
    const firstNode = itemsInitial[0];

    // Second call without data change should preserve exact DOM nodes (no flickering/blinking)
    renderNotificationCenter();
    const itemsSecond = list.querySelectorAll('.notif-center-item');
    expect(itemsSecond.length).toBe(2);
    expect(itemsSecond[0]).toBe(firstNode);
  });

  it('handles single click via event delegation to open Event Detail modal and mark event as checked', () => {
    window.openEventDetailModal = vi.fn();
    const testEv = { ts: 1791396000, level: 'error', title: 'Disk Offline', message: 'Disk sdc unplugged' };
    state.latestStats = { events: [testEv] };

    const list = document.getElementById('notif-center-list');
    list._lastRenderedSignature = null;
    renderNotificationCenter();

    const item = list.querySelector('.notif-center-item');
    expect(item).not.toBeNull();
    expect(isEventChecked(testEv)).toBe(false);

    // Single click
    item.click();

    expect(isEventChecked(testEv)).toBe(true);
    expect(window.openEventDetailModal).toHaveBeenCalledWith(testEv);
  });

  it('saves and restores open window states across simulated browser refreshes', () => {
    DockManager.windows = {
      fm: { closed: false, minimized: false },
      management: { closed: false, minimized: true }
    };
    DockManager.activeId = 'fm';

    // Notification center open
    const notifPanel = document.getElementById('notif-center-panel');
    notifPanel.style.display = 'flex';

    saveOpenWindowsState();

    const raw = localStorage.getItem(OPEN_WINDOWS_KEY);
    expect(raw).toBeDefined();
    const parsed = JSON.parse(raw);
    expect(parsed.activeId).toBe('fm');
    expect(parsed.windows['fm']).toEqual({ minimized: false, open: true });
    expect(parsed.windows['management']).toEqual({ minimized: true, open: true, activePane: 'hub' });
    expect(parsed.windows['notif']).toEqual({ minimized: false, open: true });

    // Simulate reload: clear in-memory state
    DockManager.windows = {};
    DockManager.activeId = null;
    notifPanel.style.display = 'none';

    // Mock launch functions
    const origFmLaunch = KNOWN_APPS.fm.launch;
    const origMgmtLaunch = KNOWN_APPS.management.launch;
    const fmLaunch = vi.fn();
    const mgmtLaunch = vi.fn();
    const notifLaunch = vi.fn();
    KNOWN_APPS.fm.launch = fmLaunch;
    KNOWN_APPS.management.launch = mgmtLaunch;
    window.toggleNotificationCenter = notifLaunch;

    try {
      restoreOpenWindowsState();

      expect(fmLaunch).toHaveBeenCalled();
      expect(mgmtLaunch).toHaveBeenCalled();
      expect(notifLaunch).toHaveBeenCalled();
    } finally {
      KNOWN_APPS.fm.launch = origFmLaunch;
      KNOWN_APPS.management.launch = origMgmtLaunch;
    }
  });

  it('preserves open windows across page reload without minimizing to dock', () => {
    const { setWindowRestorationComplete } = window;
    
    // Save state where management (Services/Docker) and fm are OPEN on desktop (not minimized)
    localStorage.setItem(OPEN_WINDOWS_KEY, JSON.stringify({
      activeId: 'management',
      windows: {
        management: { open: true, minimized: false, activePane: 'mgmt-pane-docker' },
        fm: { open: true, minimized: false, activePath: '/mnt/user/appdata' }
      }
    }));

    // Simulate app boot sequence: guard is active
    setWindowRestorationComplete(false);

    // During boot, background registrations occur with initialMinimized = true
    const dummyOverlay = document.createElement('div');
    DockManager.register('console', dummyOverlay, '#i-screen', 'Console', true);

    // Verify localStorage was NOT wiped clean by registration during boot
    const rawDuringBoot = JSON.parse(localStorage.getItem(OPEN_WINDOWS_KEY));
    expect(rawDuringBoot.windows['management']).toBeDefined();
    expect(rawDuringBoot.windows['management'].open).toBe(true);
    expect(rawDuringBoot.windows['management'].minimized).toBe(false);

    // Now restoreOpenWindowsState executes at end of boot
    const mgmtOpenSpy = vi.fn();
    const fmOpenSpy = vi.fn();
    window.openManagementWindow = mgmtOpenSpy;
    window.openFileManager = fmOpenSpy;

    restoreOpenWindowsState();

    expect(mgmtOpenSpy).toHaveBeenCalledWith('mgmt-pane-docker');
    expect(fmOpenSpy).toHaveBeenCalledWith('/mnt/user/appdata');
    
    // Verify windows did NOT get minimized
    expect(DockManager.windows['management']?.minimized).toBeFalsy();
    expect(DockManager.windows['fm']?.minimized).toBeFalsy();
  });

  it('correctly applies saved bounds and handles bidirectional ID aliases', () => {
    saveWindowBounds('fm', { left: 140, top: 90, width: 620, height: 480, snapped: 'maximize' });

    const winEl = document.createElement('div');
    winEl.id = 'file-manager-window';
    winEl.style.width = '300px';
    winEl.style.height = '200px';
    document.body.appendChild(winEl);

    // Apply with alias ID 'file-manager-window'
    applySavedBounds(winEl, 'file-manager-window');

    expect(winEl.dataset.snapped).toBe('maximize');
    expect(winEl.style.left).toBe('8px');
    expect(winEl.style.top).toBe('48px');
    expect(winEl.style.width).toBe('calc(100vw - 16px)');

    winEl.remove();
  });

  it('correctly preserves and restores specific subpanes (Widgets, Ingest History, Containers, About)', () => {
    const testCases = [
      { subpane: 'mgmt-pane-widgets', desc: 'Appearance -> Widgets' },
      { subpane: 'mgmt-pane-copy', desc: 'Activity Monitor -> Ingest History' },
      { subpane: 'mgmt-pane-docker', desc: 'Services -> Docker Containers' },
      { subpane: 'mgmt-pane-about', desc: 'System -> About & Updates' }
    ];

    testCases.forEach(({ subpane }) => {
      localStorage.setItem(OPEN_WINDOWS_KEY, JSON.stringify({
        activeId: 'management',
        windows: {
          management: { open: true, minimized: false, activePane: subpane }
        }
      }));

      const mgmtOpenSpy = vi.fn();
      window.openManagementWindow = mgmtOpenSpy;

      restoreOpenWindowsState();

      expect(mgmtOpenSpy).toHaveBeenCalledWith(subpane);
    });
  });

  it('openManagementWindow applies desired section and cleans up zettnas-mgmt-early-style without flashing HUB', () => {
    // Set up minimal DOM for Management window
    document.body.innerHTML = `
      <style id="zettnas-mgmt-early-style">.test { color: red; }</style>
      <div id="management-modal-overlay" class="smart-modal-backdrop" style="display: none;">
        <div id="management-window" class="smart-modal-window">
          <div id="management-window-header"></div>
          <button id="management-close"></button>
          <aside class="mgmt-sidebar">
            <button class="mgmt-sidebar-item active" data-mgmt-target="management-hub-view">HUB</button>
            <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-wallpaper">Appearance</button>
          </aside>
          <div id="management-hub-view" style="display: grid;"></div>
          <div id="management-detail-container" style="display: none;">
            <div id="mgmt-sec-wallpaper" class="mgmt-detail-card" style="display: none;">
              <button class="mgmt-inner-tab" data-tab-target="mgmt-pane-wallpaper">Wallpaper</button>
              <button class="mgmt-inner-tab" data-tab-target="mgmt-pane-widgets">Widgets</button>
              <div id="mgmt-pane-wallpaper" class="mgmt-tab-pane"></div>
              <div id="mgmt-pane-widgets" class="mgmt-tab-pane"></div>
            </div>
          </div>
        </div>
      </div>
    `;

    // Re-initialize management component with new DOM
    initManagement();

    expect(document.getElementById('zettnas-mgmt-early-style')).not.toBeNull();

    // Call openManagementWindow with 'mgmt-pane-widgets'
    window.openManagementWindow('mgmt-pane-widgets');

    // Early style should have been removed
    expect(document.getElementById('zettnas-mgmt-early-style')).toBeNull();

    // HUB button must NOT be active; Appearance button must be active
    const hubBtn = document.querySelector('.mgmt-sidebar-item[data-mgmt-target="management-hub-view"]');
    const appBtn = document.querySelector('.mgmt-sidebar-item[data-mgmt-target="mgmt-sec-wallpaper"]');
    expect(hubBtn.classList.contains('active')).toBe(false);
    expect(appBtn.classList.contains('active')).toBe(true);

    // Hub view must be hidden, detail container visible, wallpaper card visible
    expect(document.getElementById('management-hub-view').style.display).toBe('none');
    expect(document.getElementById('management-detail-container').style.display).toBe('block');
    expect(document.getElementById('mgmt-sec-wallpaper').style.display).toBe('block');

    // Widgets inner tab must be active and widgets pane displayed
    const widgetsTab = document.querySelector('.mgmt-inner-tab[data-tab-target="mgmt-pane-widgets"]');
    const widgetsPane = document.getElementById('mgmt-pane-widgets');
    expect(widgetsTab.classList.contains('active')).toBe(true);
    expect(widgetsPane.style.display).toBe('block');
  });
});

