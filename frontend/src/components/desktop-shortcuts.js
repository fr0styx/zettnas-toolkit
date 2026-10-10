/**
 * ZettNAS Toolkit - Desktop Shortcuts & Icon Management Engine
 * Allows users to add, manage, and remove shortcuts for core system apps
 * (Containers, Storage, Activity Monitor, Hardware Profiles, UPS, Settings, Notifications)
 * and custom Web / URL bookmarks directly on their desktop workspace.
 */

import { showToast } from '../toast.js';
import { escapeHtml } from '../utils.js';
import { ZettEventBus } from '../event-bus.js';

export const SHORTCUTS_STORAGE_KEY = 'zettnas_custom_desktop_shortcuts_v1';
export const POSITIONS_STORAGE_KEY = 'zettnas_desktop_icon_positions_v3';

export const SYSTEM_SHORTCUTS = [
  {
    id: 'containers-desktop-icon',
    name: 'Containers',
    title: 'Apps & Containers',
    desc: 'Manage Docker containers, Compose stacks, app catalog, and live container terminal.',
    icon: '#i-chip',
    svg: true,
    color: '#00f0ff',
    targetSection: 'mgmt-sec-docker',
    targetPane: 'mgmt-pane-docker',
    badge: 'Docker'
  },
  {
    id: 'storage-desktop-icon',
    name: 'Storage & Pools',
    title: 'Storage & Chassis',
    desc: 'Chassis digital twin, ZFS/Btrfs pools, SMB/NFS network shares, and cloud remotes.',
    icon: '#i-storage',
    svg: true,
    color: '#38bdf8',
    targetSection: 'mgmt-sec-storage',
    targetPane: 'mgmt-pane-storage-topo',
    badge: 'ZFS/Btrfs'
  },
  {
    id: 'activity-desktop-icon',
    name: 'Activity Monitor',
    title: 'Activity & Telemetry',
    desc: 'Real-time CPU, RAM, network bandwidth graphs, and media auto-ingest logs.',
    icon: '#i-bolt',
    svg: true,
    color: '#fbbf24',
    targetSection: 'mgmt-sec-activity',
    targetPane: 'mgmt-pane-metrics',
    badge: 'Telemetry'
  },
  {
    id: 'hardware-desktop-icon',
    name: 'Hardware & Fans',
    title: 'Hardware & Acoustic Profiles',
    desc: 'Acoustic profiles, custom zero-RPM fan curves, and host subsystems.',
    icon: '#i-fan',
    svg: true,
    color: '#34d399',
    targetSection: 'mgmt-sec-hardware',
    badge: 'Fans'
  },
  {
    id: 'ups-desktop-icon',
    name: 'UPS & Power',
    title: 'UPS & Power Integrity',
    desc: 'Battery health, runtime estimation, load wattage, and NUT daemon telemetry.',
    icon: '#i-sliders',
    svg: true,
    color: '#a78bfa',
    targetSection: 'mgmt-sec-ups',
    badge: 'NUT'
  },
  {
    id: 'settings-desktop-icon',
    name: 'System Settings',
    title: 'System & Security',
    desc: 'User accounts, RBAC, API tokens, master credentials, configuration backups, and updates.',
    icon: '#i-users',
    svg: true,
    color: '#f472b6',
    targetSection: 'mgmt-sec-system-group',
    badge: 'RBAC'
  },
  {
    id: 'notifications-desktop-icon',
    name: 'Notifications',
    title: 'Notifications & Alerts',
    desc: 'Configure Discord, Telegram, Email, ntfy alerting channels and event rules.',
    icon: '#i-bell',
    svg: true,
    color: '#f87171',
    targetSection: 'mgmt-sec-system-group',
    targetPane: 'mgmt-pane-notifications',
    badge: 'Alerts'
  }
];

export function getCustomShortcuts() {
  try {
    const raw = localStorage.getItem(SHORTCUTS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    console.warn('[SHORTCUTS] Failed to read stored custom shortcuts:', err);
    return [];
  }
}

export function saveCustomShortcuts(shortcuts) {
  try {
    localStorage.setItem(SHORTCUTS_STORAGE_KEY, JSON.stringify(shortcuts));
  } catch (err) {
    console.warn('[SHORTCUTS] Failed to save custom shortcuts:', err);
  }
}

export function isShortcutActive(id) {
  const current = getCustomShortcuts();
  return current.some((s) => s.id === id);
}

/**
 * Calculates next available grid slot on desktop to prevent overlapping
 */
export function calculateNextAvailablePosition() {
  const GRID_X = 140;
  const GRID_Y = 112;
  const OFFSET_X = 24;
  const OFFSET_Y = 77;
  const maxH = typeof window !== 'undefined' ? window.innerHeight : 900;
  const maxRows = Math.max(3, Math.floor((maxH - OFFSET_Y - 70) / GRID_Y));

  // Collect occupied grid slots
  const occupied = new Set();
  try {
    const raw = localStorage.getItem(POSITIONS_STORAGE_KEY);
    if (raw) {
      const positions = JSON.parse(raw) || {};
      Object.values(positions).forEach((pos) => {
        if (pos && typeof pos.left === 'number' && typeof pos.top === 'number') {
          const col = Math.round((pos.left - OFFSET_X) / GRID_X);
          const row = Math.round((pos.top - OFFSET_Y) / GRID_Y);
          occupied.add(`${col},${row}`);
        }
      });
    }
  } catch (e) {}

  // Find first unoccupied slot
  for (let col = 0; col < 8; col++) {
    for (let row = 0; row < maxRows; row++) {
      const key = `${col},${row}`;
      if (!occupied.has(key)) {
        return {
          left: OFFSET_X + col * GRID_X,
          top: OFFSET_Y + row * GRID_Y
        };
      }
    }
  }

  return { left: OFFSET_X, top: OFFSET_Y + 4 * GRID_Y };
}

/**
 * Creates the DOM element for a desktop shortcut
 */
export function createShortcutElement(shortcut) {
  const el = document.createElement('div');
  el.className = 'chassis-hero-box chassis-desktop-icon custom-desktop-shortcut';
  el.id = shortcut.id;
  el.setAttribute('role', 'button');
  el.setAttribute('tabindex', '0');
  el.title = shortcut.title || shortcut.name;
  el.dataset.shortcutId = shortcut.id;

  const iconInner = shortcut.svg
    ? `<svg class="console-hero-icon" style="${shortcut.color ? `color:${shortcut.color};` : ''}"><use href="${shortcut.icon}"/></svg>`
    : `<span style="font-size:24px;">${escapeHtml(shortcut.icon || '🔗')}</span>`;

  const dotStyle = shortcut.color
    ? `background:${shortcut.color}; box-shadow:0 0 6px ${shortcut.color};`
    : '';

  el.innerHTML = `
    <div class="console-hero-box">
      ${iconInner}
    </div>
    <div class="desktop-icon-label">
      <span class="icon-dot-status" style="${dotStyle}"></span>
      <span class="icon-text">${escapeHtml(shortcut.name)}</span>
    </div>
  `;

  // Attach execution click listener
  el.addEventListener('click', (e) => {
    // Avoid launching if dragged
    if (el.classList.contains('dragging')) return;
    launchShortcut(shortcut);
  });

  return el;
}

/**
 * Launches the shortcut action
 */
export function launchShortcut(shortcut) {
  if (shortcut.type === 'url') {
    if (shortcut.url) {
      window.open(shortcut.url, '_blank', 'noopener,noreferrer');
    }
    return;
  }

  let targetSection = shortcut.targetSection;
  let targetPane = shortcut.targetPane;

  // Backwards compatibility normalization for storage shortcut
  if (shortcut.id === 'storage-desktop-icon' && (targetPane === 'mgmt-pane-chassis' || !targetPane)) {
    targetPane = 'mgmt-pane-storage-topo';
    targetSection = 'mgmt-sec-storage';
  }

  // System shortcut launch
  if (typeof window.openManagementSection === 'function' && targetPane) {
    window.openManagementSection(targetSection, targetPane);
  } else if (typeof window.openManagementWindow === 'function') {
    window.openManagementWindow(targetPane || targetSection);
  } else {
    ZettEventBus.emit('window:open', {
      id: 'management-window',
      section: targetSection,
      pane: targetPane
    });
  }
}

/**
 * Adds a shortcut to desktop and persists state
 */
export function addDesktopShortcut(shortcutDef) {
  const current = getCustomShortcuts();
  if (current.some((s) => s.id === shortcutDef.id)) {
    showToast(`Shortcut "${shortcutDef.name}" is already on your desktop.`, 'info');
    return false;
  }

  // Calculate placement position
  const nextPos = calculateNextAvailablePosition();

  // Save to saved positions
  try {
    const rawPos = localStorage.getItem(POSITIONS_STORAGE_KEY);
    const posObj = rawPos ? JSON.parse(rawPos) : {};
    posObj[shortcutDef.id] = nextPos;
    localStorage.setItem(POSITIONS_STORAGE_KEY, JSON.stringify(posObj));
  } catch (e) {}

  current.push(shortcutDef);
  saveCustomShortcuts(current);

  // Render on desktop if container exists
  const container = document.getElementById('desktop-icons-container');
  if (container) {
    const el = createShortcutElement(shortcutDef);
    el.style.position = 'fixed';
    el.style.left = `${nextPos.left}px`;
    el.style.top = `${nextPos.top}px`;
    container.appendChild(el);

    // Wire dragging if window.makeDesktopIconDraggable exists
    if (typeof window.makeDesktopIconDraggable === 'function') {
      window.makeDesktopIconDraggable(el, shortcutDef.id);
    }
  }

  showToast(`Added "${shortcutDef.name}" to desktop!`, 'success');
  return true;
}

/**
 * Removes a shortcut from desktop
 */
export function removeDesktopShortcut(shortcutId) {
  let current = getCustomShortcuts();
  const toRemove = current.find((s) => s.id === shortcutId);
  current = current.filter((s) => s.id !== shortcutId);
  saveCustomShortcuts(current);

  // Remove position
  try {
    const rawPos = localStorage.getItem(POSITIONS_STORAGE_KEY);
    if (rawPos) {
      const posObj = JSON.parse(rawPos) || {};
      delete posObj[shortcutId];
      localStorage.setItem(POSITIONS_STORAGE_KEY, JSON.stringify(posObj));
    }
  } catch (e) {}

  // Remove DOM element
  const el = document.getElementById(shortcutId);
  if (el) {
    el.classList.add('removing');
    setTimeout(() => el.remove(), 120);
  }

  const name = toRemove ? toRemove.name : 'Shortcut';
  showToast(`Removed "${name}" from desktop.`, 'info');

  // Update modal toggles if open
  updateAddModalButtons();
  return true;
}

/**
 * Initializes all stored custom desktop shortcuts on boot
 */
export function initDesktopShortcuts() {
  const container = document.getElementById('desktop-icons-container');
  if (!container) return;

  const shortcuts = getCustomShortcuts();
  shortcuts.forEach((sc) => {
    if (!document.getElementById(sc.id)) {
      const el = createShortcutElement(sc);
      container.appendChild(el);
    }
  });
}

/**
 * Open the Add Desktop Shortcut Modal
 */
export function openAddDesktopShortcutModal() {
  let overlay = document.getElementById('add-desktop-shortcut-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'add-desktop-shortcut-overlay';
    overlay.className = 'smart-modal-backdrop';
    overlay.style.cssText = 'display:none; z-index:99999;';

    overlay.innerHTML = `
      <div class="smart-modal-window" style="max-width:580px; width:92%; max-height:85vh; display:flex; flex-direction:column; background:rgba(15,23,42,0.92); backdrop-filter:blur(24px); -webkit-backdrop-filter:blur(24px); border:1px solid rgba(255,255,255,0.14); border-radius:16px; box-shadow:0 24px 60px rgba(0,0,0,0.85), 0 0 35px rgba(0,240,255,0.12); overflow:hidden;">
        <!-- Header -->
        <div class="smart-modal-header" style="display:flex; justify-content:space-between; align-items:center; padding:16px 20px; border-bottom:1px solid rgba(255,255,255,0.08); background:rgba(255,255,255,0.02);">
          <div style="display:flex; align-items:center; gap:10px;">
            <span style="font-size:18px;">➕</span>
            <div>
              <div style="font-size:14px; font-weight:700; color:#fff;">Add Desktop Shortcut</div>
              <div style="font-size:11px; color:var(--muted);">Place quick-access shortcuts on your desktop workspace</div>
            </div>
          </div>
          <button class="win-btn close-btn" id="btn-close-add-shortcut" title="Close" aria-label="Close" style="width:16px; height:16px; border-radius:50%; background:#ff5f56; border:none; cursor:pointer;"></button>
        </div>

        <!-- Tab Switcher -->
        <div style="display:flex; gap:8px; padding:12px 20px 8px; border-bottom:1px solid rgba(255,255,255,0.06);">
          <button class="btn-pill-toggle active" id="tab-btn-system-shortcuts" style="padding:5px 12px; font-size:11.5px; font-weight:700;">📦 System Apps & Dashboards</button>
          <button class="btn-pill-toggle" id="tab-btn-custom-shortcut" style="padding:5px 12px; font-size:11.5px; font-weight:700;">🔗 Custom URL / Bookmark</button>
        </div>

        <!-- Body: Tab 1 System Apps -->
        <div id="pane-system-shortcuts" style="padding:16px 20px; overflow-y:auto; max-height:55vh; display:flex; flex-direction:column; gap:8px;">
          <!-- Dynamically populated -->
        </div>

        <!-- Body: Tab 2 Custom URL -->
        <div id="pane-custom-shortcut" style="padding:20px; display:none; flex-direction:column; gap:14px;">
          <div>
            <label style="font-size:11px; font-weight:700; color:#cbd5e1; display:block; margin-bottom:4px;">Shortcut Name</label>
            <input type="text" id="input-custom-shortcut-name" class="tz-text-input" placeholder="e.g. Plex, Home Assistant, Pi-hole, Proxmox..." style="width:100%; padding:8px 12px; font-size:12px; border-radius:6px; background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.12); color:#fff;">
          </div>
          <div>
            <label style="font-size:11px; font-weight:700; color:#cbd5e1; display:block; margin-bottom:4px;">Target URL</label>
            <input type="url" id="input-custom-shortcut-url" class="tz-text-input" placeholder="http://10.40.30.249:8123 or https://..." style="width:100%; padding:8px 12px; font-size:12px; border-radius:6px; background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.12); color:#fff; font-family:var(--font-mono, monospace);">
          </div>
          <div>
            <label style="font-size:11px; font-weight:700; color:#cbd5e1; display:block; margin-bottom:6px;">Select Icon / Emoji</label>
            <div style="display:flex; flex-wrap:wrap; gap:6px;" id="custom-shortcut-emojis">
              ${['🌐', '🏠', '🎬', '🛡️', '📦', '⚡', '🔌', '🚀', '🎮', '🎵', '💾', '📊', '📡', '🛠️'].map((emoji, idx) => `
                <button type="button" class="btn-emoji-chip ${idx === 0 ? 'active' : ''}" data-emoji="${emoji}" style="padding:6px 10px; font-size:16px; background:${idx === 0 ? 'rgba(0,240,255,0.2)' : 'rgba(255,255,255,0.05)'}; border:1px solid ${idx === 0 ? 'rgba(0,240,255,0.6)' : 'rgba(255,255,255,0.1)'}; border-radius:6px; cursor:pointer;">${emoji}</button>
              `).join('')}
            </div>
          </div>
          <button id="btn-save-custom-shortcut" style="margin-top:6px; padding:10px 16px; border-radius:8px; font-size:12px; font-weight:700; background:linear-gradient(135deg, #0ea5e9, #25c2a0); color:#fff; border:1px solid #0ea5e9; cursor:pointer; box-shadow:0 4px 14px rgba(14,165,233,0.3);">
            ✨ Add Shortcut to Desktop
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    // Wire close
    overlay.querySelector('#btn-close-add-shortcut')?.addEventListener('click', closeAddDesktopShortcutModal);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeAddDesktopShortcutModal();
    });

    // Wire tab switches
    const tabSystem = overlay.querySelector('#tab-btn-system-shortcuts');
    const tabCustom = overlay.querySelector('#tab-btn-custom-shortcut');
    const paneSystem = overlay.querySelector('#pane-system-shortcuts');
    const paneCustom = overlay.querySelector('#pane-custom-shortcut');

    tabSystem?.addEventListener('click', () => {
      tabSystem.classList.add('active');
      tabCustom.classList.remove('active');
      paneSystem.style.display = 'flex';
      paneCustom.style.display = 'none';
    });

    tabCustom?.addEventListener('click', () => {
      tabCustom.classList.add('active');
      tabSystem.classList.remove('active');
      paneSystem.style.display = 'none';
      paneCustom.style.display = 'flex';
    });

    // Wire emoji picker chips
    let selectedEmoji = '🌐';
    overlay.querySelectorAll('.btn-emoji-chip').forEach((btn) => {
      btn.addEventListener('click', () => {
        overlay.querySelectorAll('.btn-emoji-chip').forEach((b) => {
          b.style.background = 'rgba(255,255,255,0.05)';
          b.style.borderColor = 'rgba(255,255,255,0.1)';
        });
        btn.style.background = 'rgba(0,240,255,0.2)';
        btn.style.borderColor = 'rgba(0,240,255,0.6)';
        selectedEmoji = btn.dataset.emoji || '🌐';
      });
    });

    // Wire custom shortcut save
    overlay.querySelector('#btn-save-custom-shortcut')?.addEventListener('click', () => {
      const nameInput = overlay.querySelector('#input-custom-shortcut-name');
      const urlInput = overlay.querySelector('#input-custom-shortcut-url');
      const name = nameInput ? nameInput.value.trim() : '';
      const url = urlInput ? urlInput.value.trim() : '';

      if (!name || !url) {
        showToast('Please provide both a shortcut name and URL.', 'warn');
        return;
      }

      const customDef = {
        id: `custom-shortcut-${Date.now()}`,
        type: 'url',
        name,
        title: name,
        url,
        icon: selectedEmoji,
        svg: false,
        color: '#00f0ff'
      };

      addDesktopShortcut(customDef);
      if (nameInput) nameInput.value = '';
      if (urlInput) urlInput.value = '';
      closeAddDesktopShortcutModal();
    });
  }

  // Populate system shortcuts list
  renderSystemShortcutsList(overlay);

  overlay.style.display = 'flex';
  overlay.classList.add('open');
}

export function closeAddDesktopShortcutModal() {
  const overlay = document.getElementById('add-desktop-shortcut-overlay');
  if (overlay) {
    overlay.style.display = 'none';
    overlay.classList.remove('open');
  }
}

function renderSystemShortcutsList(overlay) {
  const container = overlay.querySelector('#pane-system-shortcuts');
  if (!container) return;

  const currentShortcuts = getCustomShortcuts();
  const activeIds = new Set(currentShortcuts.map((s) => s.id));

  container.innerHTML = SYSTEM_SHORTCUTS.map((s) => {
    const isActive = activeIds.has(s.id);
    return `
      <div class="shortcut-system-card" style="display:flex; align-items:center; justify-content:space-between; padding:10px 14px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:10px; gap:12px;">
        <div style="display:flex; align-items:center; gap:12px; min-width:0;">
          <div style="width:40px; height:40px; border-radius:8px; display:flex; align-items:center; justify-content:center; background:linear-gradient(135deg, rgba(0,240,255,0.12) 0%, rgba(37,194,160,0.08) 100%); border:1px solid rgba(0,240,255,0.3); color:${s.color}; flex-shrink:0;">
            <svg style="width:20px; height:20px; fill:currentColor;"><use href="${s.icon}"/></svg>
          </div>
          <div style="min-width:0;">
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="font-size:13px; font-weight:700; color:#fff;">${escapeHtml(s.name)}</span>
              ${s.badge ? `<span style="font-size:9px; padding:1px 5px; border-radius:3px; background:rgba(255,255,255,0.08); color:var(--muted); font-family:var(--font-mono, monospace); text-transform:uppercase;">${escapeHtml(s.badge)}</span>` : ''}
            </div>
            <div style="font-size:11px; color:var(--muted); line-height:1.35; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(s.desc)}</div>
          </div>
        </div>

        <button class="btn-pill-toggle shortcut-toggle-btn ${isActive ? 'active' : ''}" data-shortcut-id="${s.id}" style="flex-shrink:0; padding:5px 12px; font-size:11px; font-weight:700; cursor:pointer; ${isActive ? 'color:#22c55e; border-color:rgba(34,197,94,0.4); background:rgba(34,197,94,0.14);' : 'color:#38bdf8; border-color:rgba(56,189,248,0.4); background:rgba(14,165,233,0.12);'}">
          ${isActive ? '✓ On Desktop' : '+ Add to Desktop'}
        </button>
      </div>
    `;
  }).join('');

  // Wire toggle buttons
  container.querySelectorAll('.shortcut-toggle-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const scId = btn.dataset.shortcutId;
      const scDef = SYSTEM_SHORTCUTS.find((s) => s.id === scId);
      if (!scDef) return;

      if (isShortcutActive(scId)) {
        removeDesktopShortcut(scId);
        btn.classList.remove('active');
        btn.textContent = '+ Add to Desktop';
        btn.style.color = '#38bdf8';
        btn.style.borderColor = 'rgba(56,189,248,0.4)';
        btn.style.background = 'rgba(14,165,233,0.12)';
      } else {
        addDesktopShortcut({
          id: scDef.id,
          type: 'system',
          name: scDef.name,
          title: scDef.title,
          desc: scDef.desc,
          icon: scDef.icon,
          svg: scDef.svg,
          color: scDef.color,
          targetSection: scDef.targetSection,
          targetPane: scDef.targetPane
        });
        btn.classList.add('active');
        btn.textContent = '✓ On Desktop';
        btn.style.color = '#22c55e';
        btn.style.borderColor = 'rgba(34,197,94,0.4)';
        btn.style.background = 'rgba(34,197,94,0.14)';
      }
    });
  });
}

function updateAddModalButtons() {
  const overlay = document.getElementById('add-desktop-shortcut-overlay');
  if (!overlay || overlay.style.display === 'none') return;
  renderSystemShortcutsList(overlay);
}

export function _resetShortcutsForTesting() {
  localStorage.removeItem(SHORTCUTS_STORAGE_KEY);
  const overlay = document.getElementById('add-desktop-shortcut-overlay');
  if (overlay) overlay.remove();
  document.querySelectorAll('.custom-desktop-shortcut').forEach((el) => el.remove());
}
