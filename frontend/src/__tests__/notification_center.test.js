import { describe, it, expect, beforeEach, vi } from 'vitest';
import { makeDraggable, saveWindowBounds, loadSavedWindowBounds } from '../components/dock.js';
import { openEventDetailModal, closeEventDetailModal } from '../modals.js';

describe('Notification Center Draggable Window & Event Detail Inspector', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
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
});
