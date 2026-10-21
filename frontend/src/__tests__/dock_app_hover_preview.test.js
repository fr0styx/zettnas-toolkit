import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  DockManager,
  KNOWN_APPS,
  DOCK_PINNED_KEY
} from '../components/dock.js';
import { state } from '../state.js';

describe('Revamped Dock App Hover Preview Engine', () => {
  let dockContainer;
  let dockEl;

  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="os-dock-container" class="os-dock-container dock-pos-bottom">
        <div id="os-dock" class="os-dock active"></div>
      </div>
      <div id="management-window" class="management-window" style="width: 1080px; height: 680px; display: flex;">
        <div class="window-titlebar"><span>Mission Control</span></div>
        <div class="window-content"><canvas width="200" height="100"></canvas><p>Telemetry</p></div>
      </div>
      <div id="containers-manager-window" class="containers-manager-window" style="width: 1040px; height: 660px; display: none;">
        <div class="window-titlebar"><span>Containers</span></div>
        <div class="window-content"><p>Active Stacks</p></div>
      </div>
    `;

    dockContainer = document.getElementById('os-dock-container');
    dockEl = document.getElementById('os-dock');

    // Register test windows in DockManager
    const mgmtWin = document.getElementById('management-window');
    DockManager.windows['management'] = {
      id: 'management',
      el: mgmtWin,
      title: 'Mission Control',
      icon: '#i-management',
      minimized: false,
      closed: false
    };

    const containersWin = document.getElementById('containers-manager-window');
    DockManager.windows['containers'] = {
      id: 'containers',
      el: containersWin,
      title: 'Containers',
      icon: '#i-chip',
      minimized: true,
      closed: false
    };

    DockManager.render();
  });

  afterEach(() => {
    const tooltip = document.getElementById('dock-hover-tooltip');
    if (tooltip) tooltip.remove();
    vi.restoreAllMocks();
  });

  it('renders a live scaled miniature window preview for an active open application', () => {
    const mgmtItem = dockEl.querySelector('[data-window-id="management"]');
    expect(mgmtItem).not.toBeNull();

    // Trigger hover tooltip
    DockManager.showTooltip(mgmtItem, 'management', 'Mission Control', '#i-management', false, false);

    const tooltip = document.getElementById('dock-hover-tooltip');
    expect(tooltip).not.toBeNull();
    expect(tooltip.classList.contains('visible')).toBe(true);

    const badge = document.getElementById('dock-tooltip-badge');
    expect(badge.textContent).toBe('ACTIVE');
    expect(badge.classList.contains('active')).toBe(true);

    const previewContent = document.getElementById('dock-tooltip-preview-content');
    const liveContainer = previewContent.querySelector('.dock-preview-live-container');
    expect(liveContainer).not.toBeNull();

    const scaler = liveContainer.querySelector('.dock-preview-live-scaler');
    expect(scaler).not.toBeNull();
    expect(scaler.style.transform).toContain('scale(');

    // Cloned window must have stripped id attributes and removed minimized/hidden classes
    const clonedWin = scaler.querySelector('.dock-cloned-preview-win');
    expect(clonedWin).not.toBeNull();
    expect(clonedWin.getAttribute('id')).toBeNull();

    // Action chip should offer Focus / Bring to Front
    const actionChip = liveContainer.querySelector('.dock-preview-action-chip');
    expect(actionChip).not.toBeNull();
    expect(actionChip.textContent).toContain('Bring to Front');

    // Close button must be present in header for running apps
    const closeBtn = document.getElementById('dock-tooltip-close-btn');
    expect(closeBtn).not.toBeNull();
    expect(closeBtn.style.display).not.toBe('none');

    // Clicking close button closes the window
    const closeSpy = vi.spyOn(DockManager, 'closeWindow');
    closeBtn.click();
    expect(closeSpy).toHaveBeenCalledWith('management');
  });

  it('renders a live scaled miniature window preview for a minimized application with restore action', () => {
    const containersItem = dockEl.querySelector('[data-window-id="containers"]');
    expect(containersItem).not.toBeNull();

    // Hover minimized containers item
    DockManager.showTooltip(containersItem, 'containers', 'Containers', '#i-chip', true, false);

    const badge = document.getElementById('dock-tooltip-badge');
    expect(badge.textContent).toBe('MINIMIZED');
    expect(badge.classList.contains('minimized')).toBe(true);

    const previewContent = document.getElementById('dock-tooltip-preview-content');
    const actionChip = previewContent.querySelector('.dock-preview-action-chip');
    expect(actionChip).not.toBeNull();
    expect(actionChip.textContent).toContain('Restore');

    // Clicking live preview restores the minimized window
    const restoreSpy = vi.spyOn(DockManager, 'restore');
    const liveContainer = previewContent.querySelector('.dock-preview-live-container');
    liveContainer.click();
    expect(restoreSpy).toHaveBeenCalledWith('containers');
  });

  it('renders a sleek glassmorphic app splash card when an app is pinned but closed', () => {
    // Pin VM app but keep it closed
    DockManager.windows['vm'] = {
      id: 'vm',
      title: 'Virtual Machines',
      icon: '#i-vm',
      minimized: true,
      closed: true
    };
    localStorage.setItem(DOCK_PINNED_KEY, JSON.stringify(['vm']));
    DockManager.render();

    const vmItem = dockEl.querySelector('[data-window-id="vm"]');
    expect(vmItem).not.toBeNull();

    // Hover closed pinned app
    DockManager.showTooltip(vmItem, 'vm', 'Virtual Machines', '#i-vm', true, true);

    const badge = document.getElementById('dock-tooltip-badge');
    expect(badge.textContent).toBe('PINNED');
    expect(badge.classList.contains('pinned')).toBe(true);

    // Header close button is hidden for closed apps
    const closeBtn = document.getElementById('dock-tooltip-close-btn');
    expect(closeBtn.style.display).toBe('none');

    // Preview body contains splash card
    const previewContent = document.getElementById('dock-tooltip-preview-content');
    const splashCard = previewContent.querySelector('.dock-preview-app-splash');
    expect(splashCard).not.toBeNull();
    expect(splashCard.querySelector('.dock-splash-title').textContent).toBe('Virtual Machines');
    expect(splashCard.querySelector('.dock-splash-desc').textContent).toContain('KVM');

    // Action chip offers Open / Launch
    const actionChip = splashCard.querySelector('.dock-preview-action-chip');
    expect(actionChip.textContent).toContain('Click to open');

    // Clicking splash triggers launch
    const launchSpy = vi.spyOn(KNOWN_APPS.vm, 'launch');
    splashCard.click();
    expect(launchSpy).toHaveBeenCalled();
  });

  it('renders Desktop Home miniature workspace preview with open window counts', () => {
    const homeItem = dockEl.querySelector('.dock-item[aria-label*="Dashboard"]');
    expect(homeItem).not.toBeNull();

    DockManager.showTooltip(homeItem, 'home', 'Dashboard Home', '#i-globe', false, false);

    const badge = document.getElementById('dock-tooltip-badge');
    expect(badge.textContent).toBe('Desktop');

    const previewContent = document.getElementById('dock-tooltip-preview-content');
    const homeCard = previewContent.querySelector('.dock-preview-desktop-home');
    expect(homeCard).not.toBeNull();
    expect(homeCard.textContent).toContain('Desktop Workspace');
    expect(homeCard.textContent).toContain('Active Windows');
  });

  it('renders Notification Center summary feed preview with alerts', () => {
    const notifItem = dockEl.querySelector('.dock-notif-btn');
    expect(notifItem).not.toBeNull();

    state.latestStats = {
      events: [
        { ts: Math.floor(Date.now() / 1000), level: 'error', title: 'Drive Warning', message: 'Temp elevated' },
        { ts: Math.floor(Date.now() / 1000) - 60, level: 'info', title: 'Backup Done', message: 'Snapshot saved' }
      ]
    };

    DockManager.showTooltip(notifItem, 'notif', 'Notification Center', '#i-bell', false, false);

    const badge = document.getElementById('dock-tooltip-badge');
    expect(badge.textContent).toContain('UNREAD');

    const previewContent = document.getElementById('dock-tooltip-preview-content');
    const notifFeed = previewContent.querySelector('.dock-preview-notif-feed');
    expect(notifFeed).not.toBeNull();
    expect(notifFeed.textContent).toContain('Drive Warning');
    expect(notifFeed.textContent).toContain('Temp elevated');
  });

  it('dynamically computes arrow offset --arrow-x to point directly at dock items', () => {
    const mgmtItem = dockEl.querySelector('[data-window-id="management"]');
    mgmtItem.getBoundingClientRect = () => ({
      left: 350,
      top: 800,
      width: 48,
      height: 48,
      right: 398,
      bottom: 848
    });

    DockManager.showTooltip(mgmtItem, 'management', 'Mission Control', '#i-management', false, false);

    const tooltip = document.getElementById('dock-hover-tooltip');
    const arrowX = tooltip.style.getPropertyValue('--arrow-x');
    expect(arrowX).toBeTruthy();
    expect(arrowX).toMatch(/\d+px/);
  });

  it('accurately centers live preview and clears desktop window offsets (left, top, margin) on cloned windows', () => {
    // Simulate Containers window dragged to custom coordinates on desktop
    const containersWin = document.getElementById('containers-manager-window');
    containersWin.style.left = '450px';
    containersWin.style.top = '180px';
    containersWin.style.margin = '20px';
    containersWin.style.width = '1040px';
    containersWin.style.height = '660px';

    const containersItem = dockEl.querySelector('[data-window-id="containers"]');
    DockManager.showTooltip(containersItem, 'containers', 'Containers', '#i-chip', false, false);

    const previewContent = document.getElementById('dock-tooltip-preview-content');
    const liveContainer = previewContent.querySelector('.dock-preview-live-container');
    expect(liveContainer).not.toBeNull();

    const scaler = liveContainer.querySelector('.dock-preview-live-scaler');
    expect(scaler).not.toBeNull();

    // Verify scaler horizontal centering:
    // origW=1040, origH=660, scale = min(260/1040, 156/660) = 156/660 = 0.23636
    // scaledW = 1040 * (156/660) = 245.8 -> leftOffset = Math.round((260 - 245.8)/2) = 7px
    expect(scaler.style.left).toBe('7px');
    expect(scaler.style.top).toBe('0px');

    // Cloned window must have left, top, margin, transform reset to 0 / none so it is not shifted to bottom-right
    const clonedWin = scaler.querySelector('.dock-cloned-preview-win');
    expect(clonedWin).not.toBeNull();
    expect(clonedWin.style.top).toBe('0px');
    expect(clonedWin.style.left).toBe('0px');
    expect(clonedWin.style.right).toBe('auto');
    expect(clonedWin.style.bottom).toBe('auto');
    expect(clonedWin.style.margin).toBe('0px');
    expect(clonedWin.style.transform).toBe('none');
  });
});

