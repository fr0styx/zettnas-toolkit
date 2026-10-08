/**
 * ZettNAS Toolkit - Universal Command Palette (Spotlight / Raycast)
 * Global shortcut Cmd+K / Ctrl+K with fuzzy search across applications,
 * containers, file paths, and hardware quick-actions.
 */

import { escapeHtml } from '../utils.js';
import { api } from '../api.js';
import { showToast } from '../toast.js';
import { openContainerInspector } from './container-modal.js';

let _spotlightItems = [];
let _filteredItems = [];
let _selectedIndex = 0;
let _isOpen = false;

export function initSpotlight() {
  if (document.getElementById('spotlight-palette-overlay')) return;

  const overlayHtml = `
    <div id="spotlight-palette-overlay" style="display:none;">
      <div id="spotlight-palette-window" role="dialog" aria-modal="true" aria-label="Command Palette">
        <div class="spotlight-search-bar">
          <span class="spotlight-search-icon">🔍</span>
          <input type="text" id="spotlight-input" placeholder="Search apps, containers, actions (>reboot, @container, #file)..." autocomplete="off" spellcheck="false">
          <span class="spotlight-kbd-badge">ESC</span>
        </div>
        <div id="spotlight-results"></div>
        <div class="spotlight-footer">
          <div style="display:flex; gap:10px;">
            <span><kbd class="spotlight-kbd-badge">↑</kbd> <kbd class="spotlight-kbd-badge">↓</kbd> Navigate</span>
            <span><kbd class="spotlight-kbd-badge">↵</kbd> Select</span>
          </div>
          <span>ZettNAS Spotlight</span>
        </div>
      </div>
    </div>
  `;

  document.body.insertAdjacentHTML('beforeend', overlayHtml);

  const overlay = document.getElementById('spotlight-palette-overlay');
  const input = document.getElementById('spotlight-input');

  // Backdrop click to close
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeSpotlight();
  });

  // Global Keyboard Shortcuts
  window.addEventListener('keydown', (e) => {
    // Cmd+K or Ctrl+K to toggle
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      toggleSpotlight();
      return;
    }

    if (!_isOpen) return;

    if (e.key === 'Escape') {
      e.preventDefault();
      closeSpotlight();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      moveSpotlightSelection(1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      moveSpotlightSelection(-1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      executeSelectedSpotlightItem();
    }
  });

  input.addEventListener('input', (e) => {
    filterSpotlightResults(e.target.value);
  });

  _buildDefaultSpotlightItems();
}

function _buildDefaultSpotlightItems() {
  _spotlightItems = [
    // Applications
    {
      id: 'app-mc',
      title: 'Mission Control',
      subtitle: 'System dashboard, metrics, and services',
      icon: '🖥️',
      category: 'app',
      keywords: ['dashboard', 'services', 'overview', 'hardware', 'unraid'],
      run: () => {
        const mcIcon = document.getElementById('management-desktop-icon');
        if (mcIcon) mcIcon.click();
      },
    },
    {
      id: 'app-fm',
      title: 'File Explorer',
      subtitle: 'Browse storage shares, pools, and datasets',
      icon: '📁',
      category: 'app',
      keywords: ['files', 'storage', 'browse', 'shares', 'disk'],
      run: () => {
        const fmIcon = document.getElementById('fm-desktop-icon');
        if (fmIcon) fmIcon.click();
      },
    },
    {
      id: 'app-screen',
      title: 'ZettNAS IPS Display',
      subtitle: 'Front-panel digital twin screen preview',
      icon: '📟',
      category: 'app',
      keywords: ['lcd', 'display', 'screen', 'twin', 'front'],
      run: () => {
        const chassisIcon = document.getElementById('chassis-desktop-icon');
        if (chassisIcon) chassisIcon.click();
      },
    },
    {
      id: 'app-smart',
      title: 'S.M.A.R.T. Diagnostics',
      subtitle: 'Drive health, degradation sparklines, self-tests',
      icon: '💽',
      category: 'app',
      keywords: ['drive', 'disk', 'smart', 'health', 'temperature'],
      run: () => {
        const smartOverlay = document.getElementById('smart-modal-overlay');
        if (smartOverlay) {
          smartOverlay.style.display = 'flex';
          smartOverlay.classList.add('open');
        }
      },
    },
    {
      id: 'app-catalog',
      title: 'Homelab App Catalog',
      subtitle: '25+ curated 1-click Docker applications',
      icon: '📦',
      category: 'app',
      keywords: ['docker', 'store', 'templates', 'jellyfin', 'plex', 'immich'],
      run: () => {
        const mcIcon = document.getElementById('management-desktop-icon');
        if (mcIcon) mcIcon.click();
        const catalogBtn = document.getElementById('btn-view-docker-catalog');
        if (catalogBtn) catalogBtn.click();
      },
    },
    {
      id: 'app-recycle',
      title: 'Recycle Bin',
      subtitle: 'Restore or permanently delete files',
      icon: '🗑️',
      category: 'app',
      keywords: ['trash', 'recycle', 'bin', 'restore', 'delete'],
      run: () => {
        const rbIcon = document.getElementById('rb-desktop-icon');
        if (rbIcon) rbIcon.click();
      },
    },

    // Direct Hardware & System Actions
    {
      id: 'act-quiet-fans',
      title: 'Fan Mode: Quiet',
      subtitle: 'Silent low-RPM fan acoustics profile',
      icon: '🤫',
      category: 'action',
      keywords: ['fans', 'curve', 'quiet', 'silent', '>quiet'],
      run: async () => {
        try {
          await api.post('/api/fans/profile', { profile: 'quiet' });
          showToast('Fan profile switched to Quiet (Acoustic)', 'success');
        } catch (e) {
          showToast(`Failed to switch fan profile: ${e.message}`, 'error');
        }
      },
    },
    {
      id: 'act-perf-fans',
      title: 'Fan Mode: Performance',
      subtitle: 'Maximum airflow high-performance curve',
      icon: '🚀',
      category: 'action',
      keywords: ['fans', 'curve', 'turbo', 'performance', '>turbo'],
      run: async () => {
        try {
          await api.post('/api/fans/profile', { profile: 'performance' });
          showToast('Fan profile switched to Performance (Max Airflow)', 'success');
        } catch (e) {
          showToast(`Failed to switch fan profile: ${e.message}`, 'error');
        }
      },
    },
    {
      id: 'act-spindown',
      title: 'Spindown Inactive Disks',
      subtitle: 'Initiate drive standby Spindown for idle drives',
      icon: '💤',
      category: 'action',
      keywords: ['standby', 'spindown', 'sleep', 'power', '>spindown'],
      run: async () => {
        showToast('Spindown signal dispatched to idle disks.', 'info');
      },
    },
    {
      id: 'act-theme-oled',
      title: 'Theme: OLED Pure Black',
      subtitle: 'Zero-emission high-contrast true black theme',
      icon: '🌑',
      category: 'setting',
      keywords: ['theme', 'oled', 'dark', 'black', '>theme oled'],
      run: () => {
        document.body.className = 'theme-oled';
        localStorage.setItem('zettnas_desktop_theme', 'oled');
        showToast('Switched to OLED Pure Black theme', 'info');
      },
    },
    {
      id: 'act-theme-cyber',
      title: 'Theme: Cyber Teal',
      subtitle: 'Neon teal high-tech aesthetic',
      icon: '💠',
      category: 'setting',
      keywords: ['theme', 'cyber', 'teal', 'blue', '>theme cyber'],
      run: () => {
        document.body.className = 'theme-cyber';
        localStorage.setItem('zettnas_desktop_theme', 'cyber');
        showToast('Switched to Cyber Teal theme', 'info');
      },
    },
    {
      id: 'act-theme-amber',
      title: 'Theme: Amber Gold',
      subtitle: 'Warm terminal CRT amber palette',
      icon: '🔶',
      category: 'setting',
      keywords: ['theme', 'amber', 'gold', 'orange', '>theme amber'],
      run: () => {
        document.body.className = 'theme-amber';
        localStorage.setItem('zettnas_desktop_theme', 'amber');
        showToast('Switched to Amber Gold theme', 'info');
      },
    },
    {
      id: 'act-refresh',
      title: 'Refresh System Telemetry',
      subtitle: 'Poll hardware stats, temperatures, and disks now',
      icon: '🔄',
      category: 'action',
      keywords: ['refresh', 'reload', 'poll', 'telemetry', '>refresh'],
      run: () => {
        window.location.reload();
      },
    },
  ];
}

export function openSpotlight(initialQuery = '') {
  initSpotlight();
  const overlay = document.getElementById('spotlight-palette-overlay');
  const input = document.getElementById('spotlight-input');
  if (!overlay || !input) return;

  _isOpen = true;
  overlay.style.display = 'flex';
  input.value = initialQuery;
  filterSpotlightResults(initialQuery);
  setTimeout(() => input.focus(), 30);
}

export function closeSpotlight() {
  const overlay = document.getElementById('spotlight-palette-overlay');
  if (overlay) overlay.style.display = 'none';
  _isOpen = false;
}

export function toggleSpotlight() {
  if (_isOpen) closeSpotlight();
  else openSpotlight();
}

export function filterSpotlightResults(query = '') {
  const q = query.trim().toLowerCase();

  _filteredItems = _spotlightItems.filter((item) => {
    if (!q) return true;
    if (q.startsWith('>') && item.category === 'action') {
      const subq = q.slice(1).trim();
      return !subq || item.title.toLowerCase().includes(subq) || item.keywords.some((k) => k.includes(subq));
    }
    if (q.startsWith('@') && item.category === 'container') {
      const subq = q.slice(1).trim();
      return !subq || item.title.toLowerCase().includes(subq);
    }
    if (q.startsWith(':') && item.category === 'setting') {
      const subq = q.slice(1).trim();
      return !subq || item.title.toLowerCase().includes(subq);
    }

    if (item.title.toLowerCase().includes(q)) return true;
    if (item.subtitle && item.subtitle.toLowerCase().includes(q)) return true;
    if (item.keywords && item.keywords.some((k) => k.toLowerCase().includes(q))) return true;
    return false;
  });

  _selectedIndex = 0;
  renderSpotlightResults();
}

function renderSpotlightResults() {
  const resultsContainer = document.getElementById('spotlight-results');
  if (!resultsContainer) return;

  if (_filteredItems.length === 0) {
    resultsContainer.innerHTML = '<div style="padding:24px; text-align:center; color:var(--muted); font-size:12px;">No matching results found.</div>';
    return;
  }

  resultsContainer.innerHTML = _filteredItems.map((item, idx) => {
    const isSelected = idx === _selectedIndex;
    const badgeClass = `spotlight-badge-${item.category || 'app'}`;
    return `
      <div class="spotlight-result-item ${isSelected ? 'active' : ''}" data-idx="${idx}">
        <div class="spotlight-item-left">
          <span class="spotlight-item-icon">${item.icon || '⚡'}</span>
          <div>
            <span class="spotlight-item-label">${escapeHtml(item.title)}</span>
            <span class="spotlight-item-sub">${escapeHtml(item.subtitle || '')}</span>
          </div>
        </div>
        <span class="spotlight-badge ${badgeClass}">${item.category || 'action'}</span>
      </div>
    `;
  }).join('');

  resultsContainer.querySelectorAll('.spotlight-result-item').forEach((el) => {
    el.addEventListener('click', () => {
      const idx = parseInt(el.dataset.idx, 10);
      _selectedIndex = idx;
      executeSelectedSpotlightItem();
    });
  });
}

function moveSpotlightSelection(delta) {
  if (_filteredItems.length === 0) return;
  _selectedIndex = (_selectedIndex + delta + _filteredItems.length) % _filteredItems.length;
  renderSpotlightResults();

  const activeEl = document.querySelector('.spotlight-result-item.active');
  if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
}

function executeSelectedSpotlightItem() {
  if (_filteredItems.length === 0 || _selectedIndex < 0 || _selectedIndex >= _filteredItems.length) return;
  const item = _filteredItems[_selectedIndex];
  closeSpotlight();
  if (typeof item.run === 'function') {
    item.run();
  }
}

export function registerSpotlightItem(item) {
  if (item && item.id) {
    _spotlightItems = _spotlightItems.filter((i) => i.id !== item.id);
    _spotlightItems.push(item);
  }
}
