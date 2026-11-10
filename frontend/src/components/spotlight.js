/**
 * ZettNAS Toolkit - Universal Command Palette (Spotlight / Raycast)
 * Global shortcut Cmd+K / Ctrl+K with fuzzy search across applications,
 * containers, file paths, and hardware quick-actions.
 */

import { escapeHtml } from '../utils.js';
import { api } from '../api.js';
import { state } from '../state.js';
import { showToast, showConfirmToast } from '../toast.js';
// loaded when first used (B6 first-load budget)
const openContainerInspector = (...args) =>
  import('./container-modal.js').then((m) => {
    m.initContainerModal();
    return m.openContainerInspector(...args);
  });

import { t } from '../i18n.js';
import { ZettEventBus } from '../event-bus.js';
import { ADVANCED_SPOTLIGHT, advancedOn } from '../advanced.js';
import { canRun, currentUser } from '../route-access.js';
// Destructive actions always ask first (FE-07).
function confirmThen(title, msg, action) {
  return new Promise((resolve, reject) => {
    showConfirmToast(title, msg, async () => {
      try {
        await action();
        resolve(true);
      } catch (e) {
        reject(e);
      }
    }, () => resolve(false));
  });
}

function emptyTrash() {
  return confirmThen(t('confirm.fs_trash_empty.title', 'Empty the Recycle Bin'), t('confirm.fs_trash_empty.msg', 'Permanently delete everything in every Recycle Bin? This can\'t be undone.'), async () => {
    try {
      await api.delete('/api/fs/trash/empty', { confirmed: true });
      showToast(t('toast.trash_emptied_storage_reclaimed', 'Recycle Bin emptied. The space is free again.'), 'success');
    } catch (e) {
      showToast(t('toast.failed_to_empty_trash', 'Could not empty the Recycle Bin: {message}', { message: e.message }), 'error');
    }
  });
}

let _spotlightItems = [];
let _filteredItems = [];
let _selectedIndex = 0;
let _isOpen = false;

export function initSpotlight() {
  if (document.getElementById('spotlight-palette-overlay')) return;

  const overlayHtml = `
    <div id="spotlight-palette-overlay" style="display:none;">
      <div id="spotlight-palette-window" role="dialog" aria-modal="true" aria-label="${t('ui.command_palette', 'Command Palette')}">
        <div class="spotlight-search-bar">
          <span class="spotlight-search-icon" aria-hidden="true">🔍</span>
          <input type="text" id="spotlight-input" role="combobox" aria-expanded="false" aria-controls="spotlight-results" aria-autocomplete="list" aria-label="${t('spotlight.label', 'Search apps, folders and actions')}" placeholder="Search apps, containers, actions (>reboot, @container, #file)..." autocomplete="off" spellcheck="false">
          <span class="spotlight-kbd-badge">ESC</span>
        </div>
        <div id="spotlight-results" role="listbox" aria-label="${t('spotlight.results', 'Results')}"></div>
        <div class="spotlight-footer">
          <div style="display:flex; gap:10px;">
            <span><kbd class="spotlight-kbd-badge">↑</kbd> <kbd class="spotlight-kbd-badge">↓</kbd> ${t('sp.nav', 'Navigate')}</span>
            <span><kbd class="spotlight-kbd-badge">↵</kbd> ${t('sp.select', 'Select')}</span>
          </div>
          <span>${t('sp.brand', 'ZettNAS Spotlight')}</span>
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

// The typed commands, the same in every language
const CMD = { snap: '>snap pool <id>', fan: '>fan <pct>%', locate: '>locate drive <dev>', isolate: '>isolate container <id>', trash: '>trash empty' };

function _buildDefaultSpotlightItems() {
  _spotlightItems = [
    // Applications
    {
      id: 'app-mc',
      title: t('dock.management', 'Settings'),
      subtitle: t('sp.mc_sub', 'System dashboard, metrics, and services'),
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
      title: t('sp.files', 'File Explorer'),
      subtitle: t('sp.files_sub', 'Browse shares, pools and datasets'),
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
      title: t('sp.lcd', 'Front screen'),
      subtitle: t('sp.lcd_sub', 'Preview of the front screen'),
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
      title: t('sp.health', 'Drive Health'),
      subtitle: t('sp.health_sub', 'Every drive: is it healthy, why, and what to do; self-tests'),
      icon: '💽',
      category: 'app',
      keywords: ['drive', 'disk', 'smart', 's.m.a.r.t', 'health', 'temperature', 'self-test', 'sectors', 'replace'],
      run: () => ZettEventBus.emit('modal:smart:open', null),
    },
    {
      id: 'app-catalog',
      title: t('sp.catalog', 'App Catalog'),
      subtitle: t('sp.catalog_sub', 'Tested apps that install in one click'),
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
      title: t('dock.recycle_bin', 'Recycle Bin'),
      subtitle: t('sp.bin_sub', 'Restore files or delete them for good'),
      icon: '🗑️',
      category: 'app',
      keywords: ['trash', 'recycle', 'bin', 'restore', 'delete'],
      run: () => {
        const rbIcon = document.getElementById('rb-desktop-icon');
        if (rbIcon) rbIcon.click();
      },
    },
    {
      id: 'app-zettai',
      title: t('sp.ai', 'Ask Zetty and photo search'),
      subtitle: t('sp.ai_sub', 'Ask about your recipes and documents, or find photos by scene or colour'),
      icon: '🧠',
      category: 'app',
      keywords: ['ai', 'rag', 'search', 'recipe', 'photos', 'pool', 'beach', 'car', 'npu', 'gpu'],
      run: () => {
        if (typeof window.openManagementWindow === 'function') {
          window.openManagementWindow('mgmt-sec-ai', 'mgmt-pane-ai-rag');
        }
      },
    },

    // Direct Hardware & System Actions
    {
      id: 'act-quiet-fans',
      title: t('sp.fan_quiet', 'Fan mode: Quiet'),
      subtitle: t('sp.fan_quiet_sub', 'Slow, quiet fans'),
      icon: '🤫',
      category: 'action',
      keywords: ['fans', 'curve', 'quiet', 'silent', '>quiet'],
      run: async () => {
        try {
          await api.post('/api/fans/profile', { profile: 'quiet' });
          showToast(t('toast.fan_profile_switched_to_quiet_acoustic', 'Fan profile switched to Quiet (Acoustic)'), 'success');
        } catch (e) {
          showToast(t('toast.failed_to_switch_fan_profile', 'Failed to switch fan profile: {message}', { message: e.message }), 'error');
        }
      },
    },
    {
      id: 'act-perf-fans',
      title: t('sp.fan_perf', 'Fan mode: Performance'),
      subtitle: t('sp.fan_perf_sub', 'Most airflow, for heavy load'),
      icon: '🚀',
      category: 'action',
      keywords: ['fans', 'curve', 'turbo', 'performance', '>turbo'],
      run: async () => {
        try {
          await api.post('/api/fans/profile', { profile: 'performance' });
          showToast(t('toast.fan_profile_switched_to_performance_max', 'Fan profile switched to Performance (Max Airflow)'), 'success');
        } catch (e) {
          showToast(t('toast.failed_to_switch_fan_profile', 'Failed to switch fan profile: {message}', { message: e.message }), 'error');
        }
      },
    },
    {
      id: 'act-spindown',
      title: t('sp.spindown', 'Spin down idle drives'),
      subtitle: t('sp.spindown_sub', 'Put idle drives into standby now'),
      icon: '💤',
      category: 'action',
      keywords: ['standby', 'spindown', 'sleep', 'power', '>spindown'],
      run: async () => {
        showToast(t('toast.spindown_signal_dispatched_to_idle_disks', 'Spindown signal dispatched to idle disks.'), 'info');
      },
    },
    {
      id: 'act-theme-oled',
      title: t('sp.theme_oled', 'Theme: pure black (OLED)'),
      subtitle: t('sp.theme_oled_sub', 'True black with high contrast'),
      icon: '🌑',
      category: 'setting',
      keywords: ['theme', 'oled', 'dark', 'black', '>theme oled'],
      run: () => {
        document.body.className = 'theme-oled';
        localStorage.setItem('kiboto_desktop_theme', 'oled');
        showToast(t('toast.switched_to_oled_pure_black_theme', 'Switched to OLED Pure Black theme'), 'info');
      },
    },
    {
      id: 'act-theme-cyber',
      title: t('sp.theme_teal', 'Theme: teal'),
      subtitle: t('sp.theme_teal_sub', 'Bright teal accents'),
      icon: '💠',
      category: 'setting',
      keywords: ['theme', 'cyber', 'teal', 'blue', '>theme cyber'],
      run: () => {
        document.body.className = 'theme-cyber';
        localStorage.setItem('kiboto_desktop_theme', 'cyber');
        showToast(t('toast.switched_to_cyber_teal_theme', 'Switched to Cyber Teal theme'), 'info');
      },
    },
    {
      id: 'act-theme-amber',
      title: t('sp.theme_amber', 'Theme: amber'),
      subtitle: t('sp.theme_amber_sub', 'Warm amber, like an old terminal'),
      icon: '🔶',
      category: 'setting',
      keywords: ['theme', 'amber', 'gold', 'orange', '>theme amber'],
      run: () => {
        document.body.className = 'theme-amber';
        localStorage.setItem('kiboto_desktop_theme', 'amber');
        showToast(t('toast.switched_to_amber_gold_theme', 'Switched to Amber Gold theme'), 'info');
      },
    },
    {
      id: 'act-refresh',
      title: t('sp.refresh', 'Refresh system readings'),
      subtitle: t('sp.refresh_sub', 'Read hardware, temperatures and drives now'),
      icon: '🔄',
      category: 'action',
      keywords: ['refresh', 'reload', 'poll', 'telemetry', '>refresh'],
      run: () => {
        window.location.reload();
      },
    },
    // Tier 2: Spotlight Natural Language Actions
    {
      id: 'act-snap-pool',
      title: `${t('sp.snap', 'Snapshot a pool')} (${CMD.snap})`,
      subtitle: t('sp.snap_sub', 'Take a snapshot of a storage pool now'),
      icon: '📸',
      category: 'action',
      keywords: ['snap', 'snapshot', 'pool', 'zfs', 'btrfs', '>snap'],
      run: () => {
        openSpotlight('>snap pool ');
      },
    },
    {
      id: 'act-fan-pct',
      title: `${t('sp.fan_set', 'Set fan speed')} (${CMD.fan})`,
      subtitle: t('sp.fan_set_sub', 'Set the fans to a percentage, e.g. >fan 75%'),
      icon: '🌀',
      category: 'action',
      keywords: ['fan', 'speed', 'pwm', 'acoustic', 'turbo', 'quiet', '>fan'],
      run: () => {
        openSpotlight('>fan ');
      },
    },
    {
      id: 'act-locate-drive',
      title: `${t('sp.locate', 'Find a drive by its light')} (${CMD.locate})`,
      subtitle: t('sp.locate_sub', 'Blink the bay light to find the drive’s slot'),
      icon: '💡',
      category: 'action',
      keywords: ['locate', 'drive', 'disk', 'led', 'bay', 'strobe', '>locate'],
      run: () => {
        openSpotlight('>locate drive ');
      },
    },
    {
      id: 'act-trash-empty',
      title: `${t('confirm.fs_trash_empty.title', 'Empty the Recycle Bin')} (${CMD.trash})`,
      subtitle: t('spotlight.empty_bins_sub', 'Permanently delete what every share\'s Recycle Bin holds'),
      icon: '🗑️',
      category: 'action',
      keywords: ['trash', 'empty', 'recycle', 'purge', 'clean', '>trash'],
      run: () => emptyTrash(),
    },
    {
      id: 'act-isolate-container',
      title: `${t('sp.isolate', 'Isolate a container')} (${CMD.isolate})`,
      subtitle: t('sp.isolate_sub', 'Stop the container and cut its network'),
      icon: '🛑',
      category: 'action',
      keywords: ['isolate', 'container', 'stop', 'docker', 'quarantine', '>isolate'],
      run: () => {
        openSpotlight('>isolate container ');
      },
    },
  ];
}

export function parseNaturalLanguageAction(rawQuery) {
  if (!rawQuery || typeof rawQuery !== 'string') return null;
  const clean = rawQuery.replace(/^>/, '').trim();
  if (!clean) return null;

  // 1. Snapshot: > snap pool <id> or > snapshot <id>
  const snapMatch = clean.match(/^(?:snap|snapshot)(?:\s+(?:pool\s+)?(\S+))?/i);
  if (snapMatch) {
    const rawTarget = snapMatch[1];
    const targetPool = (!rawTarget || rawTarget.toLowerCase() === 'pool')
      ? (state.latestStats?.storage?.pool_id || (state.latestStats?.unraid ? 'unraid_array' : 'default'))
      : rawTarget;
    return {
      id: `dyn-snap-${targetPool}`,
      title: t('sp.snap_dyn', 'Snapshot pool: {pool}', { pool: targetPool }),
      subtitle: t('sp.snap_dyn_sub', 'Take a snapshot of the pool {pool} now', { pool: targetPool }),
      icon: '📸',
      category: 'action',
      keywords: ['snap', 'snapshot', targetPool],
      run: async () => {
        try {
          const res = await api.post(`/api/storage/pools/${encodeURIComponent(targetPool)}/snapshots`, {
            name: `snap_${Date.now()}`
          });
          const snapName = res?.snapshot_name || res?.name || `snap_${Date.now()}`;
          showToast(t('toast.snapshot_created_for_pool', 'Snapshot \'{snapName}\' created for pool \'{targetPool}\'', { snapName: snapName, targetPool: targetPool }), 'success', 3500);
        } catch (e) {
          const errMsg = e?.detail || e?.message || t('storage.snapshots_by_host', 'The host system makes snapshots here, not ZettNAS');
          showToast(t('toast.snapshot_failed_for', 'Snapshot failed for \'{targetPool}\': {errMsg}', { targetPool: targetPool, errMsg: errMsg }), 'error', 4500);
        }
      }
    };
  }

  // 2. Fan override: > fan quiet / turbo / normal / <pct>%
  const fanMatch = clean.match(/^fan\s+(quiet|turbo|normal|performance|(\d+)%?)/i);
  if (fanMatch) {
    const mode = fanMatch[1].toLowerCase();
    const pct = fanMatch[2] ? parseInt(fanMatch[2], 10) : null;
    let label;
    let runFn;
    if (pct !== null) {
      label = `${pct}% PWM`;
      runFn = async () => {
        try {
          const pwmVal = Math.round((pct / 100) * 255);
          await api.post('/api/fans/manual', { pwm: pwmVal });
          showToast(t('toast.fan_speed_set_to_pwm', 'Fan speed set to {pct}% ({pwmVal} PWM)', { pct: pct, pwmVal: pwmVal }), 'success');
        } catch (e) {
          showToast(t('toast.failed_to_set_fan_speed', 'Failed to set fan speed: {message}', { message: e.message }), 'error');
        }
      };
    } else {
      const prof = mode === 'turbo' ? 'performance' : (mode === 'quiet' ? 'quiet' : 'normal');
      label = prof.toUpperCase();
      runFn = async () => {
        try {
          await api.post('/api/fans/profile', { profile: prof });
          showToast(t('toast.fan_profile_switched_to', 'Fan profile switched to {prof}', { prof: prof.toUpperCase() }), 'success');
        } catch (e) {
          showToast(t('toast.failed_to_switch_fan_profile', 'Failed to switch fan profile: {message}', { message: e.message }), 'error');
        }
      };
    }
    return {
      id: `dyn-fan-${mode}`,
      title: t('sp.fan_dyn', 'Fan speed: {label}', { label }),
      subtitle: t('sp.fan_dyn_sub', 'Set the fans to {label}', { label }),
      icon: '🌀',
      category: 'action',
      keywords: ['fan', 'speed', mode],
      run: runFn
    };
  }

  // 3. Locate drive: > locate drive <dev> or > locate <dev>
  const locateMatch = clean.match(/^locate(?:\s+drive)?\s+(\S+)/i);
  if (locateMatch) {
    const dev = locateMatch[1];
    return {
      id: `dyn-locate-${dev}`,
      title: t('sp.locate_dyn', 'Find drive: {dev}', { dev }),
      subtitle: t('sp.locate_dyn_sub', 'Blink the bay light of {dev}', { dev }),
      icon: '💡',
      category: 'action',
      keywords: ['locate', 'drive', dev],
      run: async () => {
        try {
          await api.post('/api/disk/locate', { dev, duration: 15 });
          showToast(t('toast.locate_led_strobing_on_drive_for', 'Locate LED strobing on drive {dev} for 15s', { dev: dev }), 'info');
        } catch (e) {
          if (e?.error === 'cancelled') return; // a sleeping drive stays asleep
          showToast(t('toast.failed_to_locate_drive', 'Failed to locate drive {dev}: {message}', { dev: dev, message: e.message }), 'error');
        }
      }
    };
  }

  // 4. Empty trash: > trash empty or > empty trash
  if (/^(?:trash\s+empty|empty\s+trash)/i.test(clean)) {
    return {
      id: 'dyn-trash-empty',
      title: t('confirm.fs_trash_empty.title', 'Empty the Recycle Bin'),
      subtitle: t('spotlight.empty_bins_sub', 'Permanently delete what every share\'s Recycle Bin holds'),
      icon: '🗑️',
      category: 'action',
      keywords: ['trash', 'empty', 'recycle'],
      run: () => emptyTrash()
    };
  }

  // 5. Isolate / stop container: > isolate container <id> or > isolate <id>
  const isolateMatch = clean.match(/^(?:isolate|stop)(?:\s+container)?\s+(\S+)/i);
  if (isolateMatch) {
    const cId = isolateMatch[1];
    return {
      id: `dyn-isolate-${cId}`,
      title: t('sp.isolate_dyn', 'Isolate container: {id}', { id: cId }),
      subtitle: t('sp.isolate_dyn_sub', 'Stop {id} and cut its network', { id: cId }),
      icon: '🛑',
      category: 'action',
      keywords: ['isolate', 'container', cId],
      run: async () => {
        try {
          const ok = await confirmThen(t('spotlight.stop_app', 'Stop the app'), t('spotlight.stop_app_msg', 'Stop the container {name}? It stays installed; start it again from Apps.', { name: cId }), async () => {
            await api.post(`/api/docker/containers/${encodeURIComponent(cId)}/stop`);
          });
          if (ok) showToast(t('toast.container_stopped', 'Container \'{cId}\' stopped', { cId: cId }), 'warning');
        } catch (e) {
          showToast(t('toast.failed_to_stop_container', 'Failed to stop container \'{cId}\': {message}', { cId: cId, message: e.message }), 'error');
        }
      }
    };
  }

  return null;
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

  let matched = _spotlightItems.filter((item) => {
    if (ADVANCED_SPOTLIGHT.includes(item.id) && !advancedOn()) return false; // UX-23
    if (!canRun(item.id, currentUser())) return false; // only what this account may do (NUX-5)
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

  if (q.startsWith('>')) {
    const dynamicAction = parseNaturalLanguageAction(query);
    if (dynamicAction) {
      matched = [dynamicAction, ...matched.filter((i) => i.id !== dynamicAction.id)];
    }
  } else if (/^(\?|ask:|photo:|img:|doc:)/i.test(q)) {
    const isPhoto = /^(photo:|img:)/i.test(q);
    const cleanPrompt = query.replace(/^(\?|ask:|photo:|img:|doc:)\s*/i, '').trim();
    if (cleanPrompt) {
      const aiDynamicItem = {
        id: `dyn-zettai-${isPhoto ? 'photo' : 'ask'}`,
        title: isPhoto ? t('sp.photo_dyn', 'Photo search: “{q}”', { q: cleanPrompt }) : t('sp.ask_dyn', 'Ask Zetty: “{q}”', { q: cleanPrompt }),
        subtitle: isPhoto
          ? t('sp.photo_dyn_sub', 'Find photos by scene, object or colour, without waking drives')
          : t('sp.ask_dyn_sub', 'An answer from your files, with its sources'),
        icon: isPhoto ? '🖼️' : '✨',
        category: 'ai',
        keywords: ['ai', 'rag', cleanPrompt],
        run: () => {
          if (typeof window.openManagementWindow === 'function') {
            window.openManagementWindow(
              'mgmt-sec-ai',
              isPhoto ? 'mgmt-pane-ai-visual' : 'mgmt-pane-ai-rag'
            );
            setTimeout(() => {
              if (isPhoto) {
                const visIn = document.getElementById('ai-visual-query-input');
                const visBtn = document.getElementById('btn-ai-visual-search');
                if (visIn) visIn.value = cleanPrompt;
                if (visBtn) visBtn.click();
              } else {
                const askIn = document.getElementById('ai-rag-query-input');
                const askBtn = document.getElementById('btn-ai-rag-ask');
                if (askIn) askIn.value = cleanPrompt;
                if (askBtn) askBtn.click();
              }
            }, 80);
          }
        },
      };
      matched = [aiDynamicItem, ...matched];
    }
  }

  _filteredItems = matched;
  _selectedIndex = 0;
  renderSpotlightResults();
}

function renderSpotlightResults() {
  const resultsContainer = document.getElementById('spotlight-results');
  if (!resultsContainer) return;
  // the search box tells assistive technology which result is chosen (UX-29)
  const input = document.getElementById('spotlight-input');
  if (input) {
    input.setAttribute('aria-expanded', String(_filteredItems.length > 0));
    if (_filteredItems.length) input.setAttribute('aria-activedescendant', `spotlight-opt-${_selectedIndex}`);
    else input.removeAttribute('aria-activedescendant');
  }

  if (_filteredItems.length === 0) {
    resultsContainer.innerHTML = '<div style="padding:24px; text-align:center; color:var(--muted); font-size:var(--zn-fs-xs);">' + t('sp.no_results', 'Nothing found.') + '</div>';
    return;
  }

  resultsContainer.innerHTML = _filteredItems.map((item, idx) => {
    const isSelected = idx === _selectedIndex;
    const badgeClass = `spotlight-badge-${item.category || 'app'}`;
    return `
      <div class="spotlight-result-item ${isSelected ? 'active' : ''}" data-idx="${idx}" id="spotlight-opt-${idx}" role="option" aria-selected="${isSelected}">
        <div class="spotlight-item-left">
          <span class="spotlight-item-icon" aria-hidden="true">${item.icon || '⚡'}</span>
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
