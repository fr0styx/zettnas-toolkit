import { ZettEventBus } from '../event-bus.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { openDrawer, closeDrawer } from './settings.js';
import { applyTheme } from './dashboard.js';
import { state } from '../state.js';
import { showToast } from '../toast.js';

export function initCommandPalette() {
  const container = document.createElement('div');
  container.id = 'cmd-palette-wrapper';
  container.innerHTML = `
    <div id="cmd-palette-overlay" class="cmd-palette-overlay" style="display: none;">
      <div class="cmd-palette-modal" role="dialog" aria-modal="true">
        <div class="cmd-palette-search-wrapper">
          <svg class="cmd-search-icon" viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" stroke-width="2" fill="none"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
          <input type="text" id="cmd-palette-input" placeholder="Search commands... (Cmd+K)" autocomplete="off" spellcheck="false">
          <div class="cmd-palette-hint">ESC to close</div>
        </div>
        <div class="cmd-palette-results" id="cmd-palette-results"></div>
      </div>
    </div>
  `;
  document.body.appendChild(container);

  const overlay = document.getElementById('cmd-palette-overlay');
  const input = document.getElementById('cmd-palette-input');
  const resultsContainer = document.getElementById('cmd-palette-results');
  let isOpen = false;
  let selectedIndex = 0;
  let filteredCommands = [];

  const COMMANDS = [
        { id: 'nav-fm', title: 'Open File Explorer', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>', action: () => ZettEventBus.emit('window:open', {id: 'file-manager-window'}) },
    { id: 'nav-mgmt', title: 'Open Mission Control', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect><rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect><line x1="6" y1="6" x2="6.01" y2="6"></line><line x1="6" y1="18" x2="6.01" y2="18"></line></svg>', action: () => { if(window.openManagementWindow) window.openManagementWindow(); else document.getElementById('management-desktop-icon')?.click(); } },
    { id: 'nav-console', title: 'Open ZettNAS Console', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>', action: () => { if (window.openConsoleWindow) window.openConsoleWindow(); else document.getElementById('chassis-desktop-icon')?.click(); } },
    { id: 'nav-settings', title: 'Open Hardware Settings', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>', action: () => openDrawer() },
    { id: 'nav-wizard', title: 'Open Setup Wizard', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"></path></svg>', action: () => document.getElementById('btn-launch-setup-wizard')?.click() },
    { id: 'action-mobile', title: 'Toggle Mobile Stacked Mode', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect><line x1="12" y1="18" x2="12.01" y2="18"></line></svg>', action: () => document.getElementById('mobile-view-toggle-btn')?.click() },
    { id: 'theme-cyber', title: 'Theme: Cyber (Default Dark)', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line></svg>', action: () => applyTheme('cyber') },
    { id: 'theme-amber', title: 'Theme: Amber (CRT Retro)', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line></svg>', action: () => applyTheme('amber') },
    { id: 'theme-emerald', title: 'Theme: Emerald (Matrix Green)', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"></path></svg>', action: () => applyTheme('emerald') },
    { id: 'theme-yak', title: 'Theme: Yak Express (Toastie)', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M2 12h4l3-9 5 18 3-9h5"></path></svg>', action: () => applyTheme('yak') },
    { id: 'theme-light', title: 'Theme: Light (Modern Clean)', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"></path></svg>', action: () => applyTheme('light') },
    { id: 'profile-auto', title: 'Set Acoustic Profile: Auto Dynamic', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>', action: () => setProfile('auto') },
    { id: 'profile-quiet', title: 'Set Acoustic Profile: Quiet', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><line x1="23" y1="9" x2="17" y2="15"></line><line x1="17" y1="9" x2="23" y2="15"></line></svg>', action: () => setProfile('quiet') },
    { id: 'profile-balanced', title: 'Set Acoustic Profile: Balanced', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path></svg>', action: () => setProfile('balanced') },
    { id: 'profile-performance', title: 'Set Acoustic Profile: Performance', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path></svg>', action: () => setProfile('performance') },
    { id: 'lang-en', title: 'Language: English', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>', action: () => setLanguage('en') },
    { id: 'lang-de', title: 'Language: Deutsch (German)', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>', action: () => setLanguage('de') },
    { id: 'lang-zh', title: 'Language: 中文 (Chinese)', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>', action: () => setLanguage('zh') },
    { id: 'lang-fr', title: 'Language: Français (French)', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>', action: () => setLanguage('fr') },
    { id: 'lang-es', title: 'Language: Español (Spanish)', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>', action: () => setLanguage('es') },
    { id: 'lcd-cycle', title: 'LCD: Cycle to Next Page', icon: '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polyline points="1 4 1 10 7 10"></polyline><polyline points="23 20 23 14 17 14"></polyline><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"></path></svg>', action: () => cycleLcd() }
  ];

  async function setProfile(mode) {
    try {
      await api.post('/api/system/profile', { profile: mode });
      showToast(t('action_success', 'Profile applied.'));
    } catch (e) {
      showToast(t('err_general', 'Error applying profile.'), 'error');
    }
  }

  function setLanguage(lang) {
    localStorage.setItem("zettnas_language", lang);
    window.location.reload();
  }

  async function cycleLcd() {
    try {
      await api.post('/api/lcd/cycle');
      showToast('LCD cycled to next page');
    } catch (e) {
      showToast('Error cycling LCD', 'error');
    }
  }

  function renderResults() {
    resultsContainer.innerHTML = '';
    if (filteredCommands.length === 0) {
      resultsContainer.innerHTML = `<div class="cmd-palette-empty">No commands found</div>`;
      return;
    }
    filteredCommands.forEach((cmd, idx) => {
      const el = document.createElement('div');
      el.className = `cmd-palette-item ${idx === selectedIndex ? 'selected' : ''}`;
      el.innerHTML = `
        <span class="cmd-palette-icon">${cmd.icon}</span>
        <span class="cmd-palette-title">${cmd.title}</span>
      `;
      el.addEventListener('click', () => {
        executeCommand(cmd);
      });
      el.addEventListener('mouseenter', () => {
        selectedIndex = idx;
        updateSelection();
      });
      resultsContainer.appendChild(el);
    });
    scrollIntoViewIfNeeded();
  }

  function updateSelection() {
    const items = resultsContainer.querySelectorAll('.cmd-palette-item');
    items.forEach((item, idx) => {
      if (idx === selectedIndex) {
        item.classList.add('selected');
      } else {
        item.classList.remove('selected');
      }
    });
    scrollIntoViewIfNeeded();
  }

  function scrollIntoViewIfNeeded() {
    const selected = resultsContainer.querySelector('.cmd-palette-item.selected');
    if (selected) {
      selected.scrollIntoView({ block: 'nearest' });
    }
  }

  function filterCommands(query) {
    if (!query) {
      filteredCommands = COMMANDS;
    } else {
      const q = query.toLowerCase();
      filteredCommands = COMMANDS.filter(c => c.title.toLowerCase().includes(q) || c.id.toLowerCase().includes(q));
    }
    selectedIndex = 0;
    renderResults();
  }

  function openPalette() {
    if (isOpen) return;
    isOpen = true;
    overlay.style.display = 'flex';
    input.value = '';
    filterCommands('');
    // Slight delay to ensure display: flex has applied before focusing
    setTimeout(() => input.focus(), 10);
  }

  function closePalette() {
    if (!isOpen) return;
    isOpen = false;
    overlay.style.display = 'none';
    input.blur();
  }

  function executeCommand(cmd) {
    closePalette();
    cmd.action();
  }

  input.addEventListener('input', (e) => {
    filterCommands(e.target.value);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (selectedIndex < filteredCommands.length - 1) {
        selectedIndex++;
        updateSelection();
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (selectedIndex > 0) {
        selectedIndex--;
        updateSelection();
      }
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filteredCommands.length > 0) {
        executeCommand(filteredCommands[selectedIndex]);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      closePalette();
    }
  });

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      closePalette();
    }
  });

  window.addEventListener('keydown', (e) => {
    // Cmd+K or Ctrl+K
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      isOpen ? closePalette() : openPalette();
    }
  });
}
