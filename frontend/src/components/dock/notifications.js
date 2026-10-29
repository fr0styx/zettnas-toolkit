// Notifications: which events were read, checked or cleared, the dock toast and the notification centre.
// Part of dock.js, split out by ARC-5.

import { escapeHtml } from '../../utils.js';
import { state } from '../../state.js';
import { t } from '../../i18n.js';
import { ZettEventBus } from '../../event-bus.js';
import { formatDateTime } from '../../format.js';
import { _dockPosition } from './dock-settings.js';
import { initWindowKeyboardShortcuts } from './shortcuts.js';
import { bringToFront } from './window-drag.js';
import { applySavedBounds, loadSavedWindowBounds, saveOpenWindowsState } from './window-state.js';

let lastReadEventTs = parseFloat(localStorage.getItem('zettnas_last_read_event_ts_v2') || '0');
export let clearedEventsTs = parseFloat(localStorage.getItem('zettnas_cleared_events_ts') || '0');
let currentNotifFilter = 'all';

export const CHECKED_EVENTS_KEY = 'zettnas_checked_events_v1';
export const DOCK_PINNED_KEY = 'zettnas_dock_pinned_apps_v1'; // a storage key name, not a secret: gitleaks:allow

let checkedEventKeys = new Set();
try {
  const saved = localStorage.getItem(CHECKED_EVENTS_KEY);
  if (saved) {
    checkedEventKeys = new Set(JSON.parse(saved));
  }
} catch {
  checkedEventKeys = new Set();
}

export function resetCheckedEventsState() {
  checkedEventKeys.clear();
  lastReadEventTs = 0;
  clearedEventsTs = 0;
  try {
    localStorage.removeItem(CHECKED_EVENTS_KEY);
    localStorage.removeItem('zettnas_last_read_event_ts');
    localStorage.removeItem('zettnas_last_read_event_ts_v2');
    localStorage.removeItem('zettnas_cleared_events_ts');
  } catch {}
}

export function getEventKey(e) {
  if (!e) return '';
  return e.id || `${e.ts || 0}_${e.title || ''}_${e.level || ''}`;
}

export function isEventChecked(e) {
  if (!e) return false;
  const key = getEventKey(e);
  if (checkedEventKeys.has(key)) return true;
  if (lastReadEventTs > 0 && e.ts && e.ts <= lastReadEventTs) return true;
  return false;
}

export function saveCheckedEvents() {
  try {
    const arr = Array.from(checkedEventKeys).slice(-500);
    localStorage.setItem(CHECKED_EVENTS_KEY, JSON.stringify(arr));
  } catch (err) {
    console.warn('Failed to save checked events', err);
  }
}

export function markEventChecked(e, persist = true) {
  if (!e) return;
  const key = getEventKey(e);
  checkedEventKeys.add(key);
  if (persist) {
    saveCheckedEvents();
  }
}

export function showDockToast(msg, targetId = null) {
  let container = document.getElementById('global-toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'global-toast-container';
    document.body.appendChild(container);
  }

  const dock = document.getElementById('os-dock');
  let bottomPos = 84;
  let leftPos = null;

  if (targetId) {
    const item = document.querySelector(`#os-dock [data-window-id="${targetId}"]`);
    if (item) {
      const rect = item.getBoundingClientRect();
      if (rect.top > 0) {
        bottomPos = Math.max(76, Math.round(window.innerHeight - rect.top + 14));
        leftPos = Math.max(120, Math.min(window.innerWidth - 120, Math.round(rect.left + (rect.width / 2))));
      }
    }
  }

  if (leftPos == null && dock) {
    const dockRect = dock.getBoundingClientRect();
    if (dockRect.top > 0) {
      bottomPos = Math.max(76, Math.round(window.innerHeight - dockRect.top + 14));
    }
  }

  if (_dockPosition === 'left') {
    const dockRect = dock ? dock.getBoundingClientRect() : null;
    const lPos = dockRect ? Math.round(dockRect.right + 24) : 90;
    container.style.position = 'fixed';
    container.style.bottom = '32px';
    container.style.top = 'auto';
    container.style.left = `${lPos}px`;
    container.style.transform = 'none';
  } else if (_dockPosition === 'top') {
    const dockRect = dock ? dock.getBoundingClientRect() : null;
    const tPos = dockRect ? Math.round(dockRect.bottom + 16) : 90;
    container.style.position = 'fixed';
    container.style.top = `${tPos}px`;
    container.style.bottom = 'auto';
    container.style.left = '50%';
    container.style.transform = 'translateX(-50%)';
  } else {
    container.style.position = 'fixed';
    container.style.bottom = `${bottomPos}px`;
    container.style.top = 'auto';
    container.style.left = leftPos != null ? `${leftPos}px` : '50%';
    container.style.transform = 'translateX(-50%)';
  }
  container.style.zIndex = 'var(--z-toast, 10000)';
  container.style.display = 'flex';
  container.style.flexDirection = 'column';
  container.style.alignItems = 'center';
  container.style.gap = '8px';
  container.style.pointerEvents = 'none';

  const toast = document.createElement('div');
  toast.className = 'dock-pin-toast';
  toast.style.cssText = 'background:rgba(18,25,35,0.92); border:1px solid rgba(255,255,255,0.22); backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px); color:#fff; font-size:var(--zn-fs-xs); font-weight:600; padding:6px 14px; border-radius:18px; box-shadow:0 8px 24px rgba(0,0,0,0.6), 0 0 1px rgba(255,255,255,0.2) inset; pointer-events:none; transition:opacity 0.22s cubic-bezier(0.16, 1, 0.3, 1), transform 0.22s cubic-bezier(0.16, 1, 0.3, 1); transform:translateY(8px) scale(0.96); opacity:0; white-space:nowrap;';
  toast.textContent = msg;
  container.appendChild(toast);

  requestAnimationFrame(() => {
    toast.style.transform = 'translateY(0) scale(1)';
    toast.style.opacity = '1';
  });

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(-6px) scale(0.96)';
    setTimeout(() => toast.remove(), 250);
  }, 2200);
}

export function updateNotificationBadge() {
  const badge = document.getElementById('dock-notif-badge');
  if (!badge || !state.latestStats || !state.latestStats.events) return;
  
  const events = state.latestStats.events;
  const unreadCount = events.filter((e) => !isEventChecked(e) && e.ts > clearedEventsTs).length;
  
  if (unreadCount > 0) {
    badge.textContent = unreadCount > 99 ? '99+' : unreadCount;
    badge.style.display = 'block';
  } else {
    badge.style.display = 'none';
  }
  // The badge is visual only; the count is part of the button's name for screen readers
  const btn = badge.closest('.dock-notif-btn');
  if (btn) {
    btn.setAttribute(
      'aria-label',
      unreadCount > 0
        ? t('dock.notifications_unread', 'Notification Center, {count} unread', { count: unreadCount })
        : t('dock.notifications', 'Notification Center')
    );
  }
}

window.toggleNotificationCenter = function() {
  const panel = document.getElementById('notif-center-panel');
  if (!panel) return;
  if (panel.style.display === 'none' || panel.style.display === '') {
    panel.style.display = 'flex';

    // Position window if bounds not yet saved
    const saved = loadSavedWindowBounds()['notif-center'];
    if (!saved || saved.left == null || saved.top == null) {
      const panelW = 380;
      const panelH = 500;
      const defaultLeft = Math.max(20, window.innerWidth - panelW - 24);
      const defaultTop = Math.max(56, window.innerHeight - panelH - 80);
      panel.style.position = 'fixed';
      panel.style.margin = '0';
      panel.style.bottom = 'auto';
      panel.style.right = 'auto';
      panel.style.left = `${defaultLeft}px`;
      panel.style.top = `${defaultTop}px`;
      panel.style.width = `${panelW}px`;
      panel.style.height = `${panelH}px`;
    } else {
      applySavedBounds(panel, 'notif-center');
    }

    bringToFront(panel);
    renderNotificationCenter();
    saveOpenWindowsState();
  } else {
    panel.style.display = 'none';
    saveOpenWindowsState();
  }
};

export function renderNotificationCenter() {
  const list = document.getElementById('notif-center-list');
  if (!list || !state.latestStats || !state.latestStats.events) return;
  
  let events = [...state.latestStats.events]
    .filter(e => e.ts > clearedEventsTs)
    .sort((a,b) => b.ts - a.ts);

  if (currentNotifFilter === 'error') {
    events = events.filter(e => e.level === 'error');
  } else if (currentNotifFilter === 'warning') {
    events = events.filter(e => e.level === 'warning');
  } else if (currentNotifFilter === 'info') {
    events = events.filter(e => e.level === 'info' || e.level === 'success' || !e.level);
  }
  
  if (events.length === 0) {
    const emptyMsg = currentNotifFilter === 'all'
      ? t('notif.empty', 'No recent notifications.')
      : t('notif.no_matching', 'No notifications matching filter.');
    const emptySig = `empty_${currentNotifFilter}_${clearedEventsTs}`;
    if (list._lastRenderedSignature === emptySig) return;
    list._lastRenderedSignature = emptySig;
    list.innerHTML = `<div style="padding:28px 16px; text-align:center; color:var(--muted); font-size:var(--zn-fs-xs);">${escapeHtml(emptyMsg)}</div>`;
    return;
  }
  
  const visibleEvents = events.slice(0, 50);
  const sigParts = visibleEvents.map(e => `${getEventKey(e)}:${isEventChecked(e) ? '1' : '0'}`);
  const currentSignature = `${currentNotifFilter}_${clearedEventsTs}_${visibleEvents.length}_${sigParts.join(';')}`;

  // If signature has not changed, do not touch innerHTML so hover state, transitions, and active clicks aren't lost
  if (list._lastRenderedSignature === currentSignature) {
    return;
  }
  list._lastRenderedSignature = currentSignature;

  // Set up event delegation once on list to ensure single-click always works reliably
  if (!list._clickDelegated) {
    list._clickDelegated = true;
    list.addEventListener('click', (ev) => {
      const row = ev.target.closest('.notif-center-item');
      if (!row) return;
      const eventKey = row.dataset.eventKey;
      if (!eventKey) return;
      const eventObj = row._eventData || (state.latestStats?.events || []).find(e => getEventKey(e) === eventKey);
      if (!eventObj) return;

      markEventChecked(eventObj, true);
      updateNotificationBadge();
      renderNotificationCenter();
      
      if (window.openEventDetailModal) {
        window.openEventDetailModal(eventObj);
      }
    });
  }

  list.innerHTML = '';
  visibleEvents.forEach(e => {
    const isChecked = isEventChecked(e);
    const dt = new Date(e.ts * 1000);
    let color = '#cbd5e1';
    let icon = 'ℹ️';
    if (e.level === 'error') { color = 'var(--crit)'; icon = '❌'; }
    else if (e.level === 'warning') { color = 'var(--warn)'; icon = '⚠️'; }
    else if (e.level === 'success') { color = 'var(--ok2)'; icon = '✅'; }
    
    const row = document.createElement('div');
    row.className = 'notif-center-item' + (isChecked ? ' notif-event-checked' : '');
    row.dataset.eventKey = getEventKey(e);
    row._eventData = e;
    row.style.cssText = `padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; gap: 8px; align-items: flex-start; cursor:pointer; transition: background 0.15s ease; ${isChecked ? 'opacity: 0.45; filter: grayscale(0.5); background: transparent;' : 'background: rgba(255,255,255,0.05);'}`;
    row.innerHTML = `
      <span class="notif-center-icon" style="font-size: 14px; margin-top:2px; flex-shrink:0;">${icon}</span>
      <div style="display:flex; flex-direction:column; gap:2px; flex:1; min-width:0;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div class="notif-center-title" style="font-size:var(--zn-fs-xs); font-weight:700; color:${color}; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; ${isChecked ? 'opacity:0.75;' : ''}">${escapeHtml(e.title)}</div>
          <span style="font-size:var(--zn-fs-xs); color:var(--muted); opacity:0.8; margin-left:6px; flex-shrink:0;">🔍</span>
        </div>
        <div class="notif-center-msg" style="font-size:var(--zn-fs-xs); color:${isChecked ? 'var(--muted)' : '#fff'}; line-height:1.4; word-break:break-word;">${escapeHtml(e.message)}</div>
        <div style="font-size:var(--zn-fs-xs); color:var(--muted); margin-top:2px;">${formatDateTime(dt)}</div>
      </div>
      ${!isChecked ? `<div class="notif-unread-dot" style="width:6px; height:6px; border-radius:50%; background:var(--brand, #0ea5e9); margin-left:auto; margin-top:6px; flex-shrink:0;"></div>` : ''}
    `;
    list.appendChild(row);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const markReadBtn = document.getElementById('notif-mark-read');
  if (markReadBtn) {
    markReadBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (state.latestStats && state.latestStats.events && state.latestStats.events.length > 0) {
        state.latestStats.events.forEach(ev => markEventChecked(ev, false));
        saveCheckedEvents();
        lastReadEventTs = Math.max(...state.latestStats.events.map(ev => ev.ts));
        localStorage.setItem('zettnas_last_read_event_ts_v2', lastReadEventTs.toString());
        updateNotificationBadge();
        renderNotificationCenter();
      }
    });
  }

  const clearAllBtn = document.getElementById('notif-clear-all');
  if (clearAllBtn) {
    clearAllBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      clearedEventsTs = Math.floor(Date.now() / 1000);
      localStorage.setItem('zettnas_cleared_events_ts', clearedEventsTs.toString());
      updateNotificationBadge();
      renderNotificationCenter();
    });
  }

  document.querySelectorAll('.notif-filter-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      document.querySelectorAll('.notif-filter-btn').forEach(b => {
        b.classList.remove('active');
        b.style.background = 'transparent';
        b.style.borderColor = 'transparent';
        b.style.color = b.dataset.filter === 'error' ? 'var(--crit, #ff5c5c)' : (b.dataset.filter === 'warning' ? 'var(--warn, #f5a623)' : (b.dataset.filter === 'info' ? '#93c5fd' : '#cbd5e1'));
      });
      btn.classList.add('active');
      btn.style.background = 'rgba(255,255,255,0.1)';
      btn.style.borderColor = 'rgba(255,255,255,0.15)';
      btn.style.color = '#fff';
      currentNotifFilter = btn.dataset.filter || 'all';
      renderNotificationCenter();
    });
  });
  
  const notifSettingsBtn = document.getElementById('notif-settings-btn');
  if (notifSettingsBtn) {
    notifSettingsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const panel = document.getElementById('notif-center-panel');
      if (panel) {
        panel.style.display = 'none';
        saveOpenWindowsState();
      }
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-pane-notifications');
      }
    });
  }

  const notifCloseBtn = document.getElementById('notif-close-btn');
  if (notifCloseBtn) {
    notifCloseBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const panel = document.getElementById('notif-center-panel');
      if (panel) {
        panel.style.display = 'none';
        saveOpenWindowsState();
      }
    });
  }

  initWindowKeyboardShortcuts();

  ZettEventBus.on('stats:updated', () => {
    updateNotificationBadge();
    const panel = document.getElementById('notif-center-panel');
    if (panel && panel.style.display !== 'none') {
      renderNotificationCenter();
    }
    const tooltip = document.getElementById('dock-hover-tooltip');
    if (tooltip && tooltip.classList.contains('visible') && tooltip.dataset.currentWindowId === 'notif') {
      const notifBtn = document.querySelector('.dock-notif-btn');
      if (notifBtn && window.DockManager && window.DockManager.showTooltip) {
        window.DockManager.showTooltip(notifBtn, 'notif', t('dock.notifications', 'Notification Center'), '#i-bell', false);
      }
    }
  });
});
