// Desktop icons: placement, dragging and arrangement.
// Part of dock.js, split out by ARC-5.

import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { openSpotlight, initSpotlight } from '../spotlight.js';
import { initDesktopShortcuts, removeDesktopShortcut, openAddDesktopShortcutModal } from '../desktop-shortcuts.js';
import { hideDesktopContextMenu } from '../desktop-context-menu.js';
import { KNOWN_APPS } from './apps.js';
import { initDesktopLasso } from './lasso.js';
import { restoreWindowsAfterWiden } from './window-state.js';

export function initDraggableDesktopIcons() {
  const storageKey = 'zettnas_desktop_icon_positions_v3';
  let savedPositions = {};
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw) savedPositions = JSON.parse(raw) || {};
  } catch (e) {
    savedPositions = {};
  }

  // Initialize stored custom shortcuts into DOM
  initDesktopShortcuts();

  // Desktop icons arranged vertically with equal spacing (25px top navbar gap, 25px gap between icons, pitch = 112px)
  const defaultIconConfigs = [
    { id: 'management-desktop-icon', defaultLeft: 24, defaultTop: 77 },
    { id: 'containers-desktop-icon', defaultLeft: 24, defaultTop: 189 },
    { id: 'vm-desktop-icon', defaultLeft: 24, defaultTop: 301 },
    { id: 'fm-desktop-icon', defaultLeft: 24, defaultTop: 413 },
    { id: 'rb-desktop-icon', defaultLeft: 24, defaultTop: 525 },
    { id: 'chassis-desktop-icon', defaultLeft: 24, defaultTop: 637 },
  ];

  const getAllIconElements = () => {
    const defaultIds = ['management-desktop-icon', 'containers-desktop-icon', 'vm-desktop-icon', 'fm-desktop-icon', 'rb-desktop-icon', 'chassis-desktop-icon'];
    const elements = [];
    const seen = new Set();
    defaultIds.forEach((id) => {
      const el = document.getElementById(id);
      if (el && el.style.display !== 'none' && !el.classList.contains('hidden')) {
        elements.push({ id, el });
        seen.add(id);
      }
    });
    document.querySelectorAll('#desktop-icons-container .chassis-hero-box, .chassis-workbench-stage .chassis-hero-box').forEach((el) => {
      if (el.id && !seen.has(el.id) && el.style.display !== 'none' && !el.classList.contains('hidden')) {
        elements.push({ id: el.id, el });
        seen.add(el.id);
      }
    });
    return elements;
  };

  // Desktop Icon Context Menu
  let ctxMenu = document.getElementById('desktop-ctx-menu');
  if (!ctxMenu) {
    ctxMenu = document.createElement('div');
    ctxMenu.id = 'desktop-ctx-menu';
    ctxMenu.className = 'os-context-menu desktop-context-menu';
    ctxMenu.style.display = 'none';
    document.body.appendChild(ctxMenu);
  }

  const hideMenu = (ev) => {
    if (ev && ev.target && ev.target.closest('#desktop-ctx-menu')) return;
    if (ctxMenu) ctxMenu.style.display = 'none';
    document.removeEventListener('pointerdown', hideMenu);
    document.removeEventListener('click', hideMenu);
  };

  const wireHide = () => {
    setTimeout(() => {
      document.addEventListener('pointerdown', hideMenu);
      document.addEventListener('click', hideMenu);
    }, 100);
  };

  const isPositionOccupied = (left, top, placedList, excludeId) => {
    return placedList.some((p) => {
      if (excludeId && p.id === excludeId) return false;
      return Math.abs(left - p.left) < 80 && Math.abs(top - p.top) < 70;
    });
  };

  const findNextFreeSlot = (startLeft, startTop, placedList, maxLeft, maxTop, excludeId) => {
    const GRID_X = 140;
    const GRID_Y = 112;
    const OFFSET_X = 24;
    const OFFSET_Y = 77;
    const startCol = Math.max(0, Math.round((startLeft - OFFSET_X) / GRID_X));
    const startRow = Math.max(0, Math.round((startTop - OFFSET_Y) / GRID_Y));
    const maxRows = Math.max(3, Math.floor((maxTop - OFFSET_Y) / GRID_Y) + 1);

    // 1. Try subsequent rows down the current column first
    for (let r = startRow + 1; r < maxRows; r++) {
      const testLeft = OFFSET_X + startCol * GRID_X;
      const testTop = OFFSET_Y + r * GRID_Y;
      if (testLeft <= maxLeft && testTop <= maxTop && !isPositionOccupied(testLeft, testTop, placedList, excludeId)) {
        return { left: testLeft, top: testTop };
      }
    }

    // 2. Try other columns (wrap to next columns first, then earlier columns if needed)
    for (let colOffset = 1; colOffset < 12; colOffset++) {
      const col = (startCol + colOffset) % 12;
      for (let r = 0; r < maxRows; r++) {
        const testLeft = OFFSET_X + col * GRID_X;
        const testTop = OFFSET_Y + r * GRID_Y;
        if (testLeft <= maxLeft && testTop <= maxTop && !isPositionOccupied(testLeft, testTop, placedList, excludeId)) {
          return { left: testLeft, top: testTop };
        }
      }
    }

    // 3. Fallback: nudge downwards
    let fallbackTop = startTop + GRID_Y;
    while (fallbackTop <= maxTop && isPositionOccupied(startLeft, fallbackTop, placedList, excludeId)) {
      fallbackTop += GRID_Y;
    }
    return { left: startLeft, top: Math.min(fallbackTop, maxTop) };
  };

  const alignGrid = () => {
    if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
    const GRID_X = 140;
    const GRID_Y = 112;
    const OFFSET_X = 24;
    const OFFSET_Y = 77;
    const icons = getAllIconElements();
    const placedInGrid = [];
    const maxLeft = Math.max(24, window.innerWidth - 136 - 10);
    const maxTop = Math.max(77, window.innerHeight - 136 - 70);

    icons.forEach(({ id, el }) => {
      const rect = el.getBoundingClientRect();
      let snapLeft = OFFSET_X + Math.round((rect.left - OFFSET_X) / GRID_X) * GRID_X;
      let snapTop = OFFSET_Y + Math.round((rect.top - OFFSET_Y) / GRID_Y) * GRID_Y;

      if (snapLeft < OFFSET_X) snapLeft = OFFSET_X;
      if (snapTop < OFFSET_Y) snapTop = OFFSET_Y;
      snapLeft = Math.min(maxLeft, snapLeft);
      snapTop = Math.min(maxTop, snapTop);

      if (isPositionOccupied(snapLeft, snapTop, placedInGrid, id)) {
        const freeSlot = findNextFreeSlot(snapLeft, snapTop, placedInGrid, maxLeft, maxTop, id);
        snapLeft = freeSlot.left;
        snapTop = freeSlot.top;
      }

      placedInGrid.push({ id, left: snapLeft, top: snapTop });
      el.style.left = snapLeft + 'px';
      el.style.top = snapTop + 'px';
      savedPositions[id] = { left: snapLeft, top: snapTop };
    });
    localStorage.setItem(storageKey, JSON.stringify(savedPositions));
    hideMenu();
  };
  window.alignDesktopGrid = alignGrid;

  const sortByName = () => {
    if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;
    const icons = getAllIconElements();
    let items = icons.map(({ id, el }) => {
      const nameEl = el.querySelector('.icon-text');
      const name = (nameEl ? (nameEl.innerText || nameEl.textContent) : '') || id;
      return { id, el, name: String(name || '').trim() };
    });
    // Keep Mission Control anchored first, Containers second, Virtual Machines third, sort others alphabetically
    items.sort((a, b) => {
      if (a.id === 'management-desktop-icon') return -1;
      if (b.id === 'management-desktop-icon') return 1;
      if (a.id === 'containers-desktop-icon') return -1;
      if (b.id === 'containers-desktop-icon') return 1;
      if (a.id === 'vm-desktop-icon') return -1;
      if (b.id === 'vm-desktop-icon') return 1;
      return a.name.localeCompare(b.name);
    });
    let currentY = 77;
    let currentX = 24;
    const GAP = 25;
    const maxH = typeof window !== 'undefined' ? window.innerHeight - 100 : 700;
    items.forEach((item) => {
      const rect = item.el.getBoundingClientRect();
      const height = rect.height > 0 ? rect.height : 87;
      if (currentY + height > maxH) {
        currentX += 140;
        currentY = 77;
      }
      item.el.style.left = `${currentX}px`;
      item.el.style.top = `${currentY}px`;
      savedPositions[item.id] = { left: currentX, top: currentY };
      currentY += height + GAP;
    });
    localStorage.setItem(storageKey, JSON.stringify(savedPositions));
    hideMenu();
  };
  window.sortDesktopIcons = sortByName;
  window.openAddDesktopShortcutModal = openAddDesktopShortcutModal;

  const wireGridAndSort = () => {
    document.getElementById('ctx-align-grid')?.addEventListener('click', alignGrid);
    document.getElementById('ctx-sort-name')?.addEventListener('click', sortByName);
  };

  document.body.addEventListener('contextmenu', (e) => {
    if (typeof e.target?.closest !== 'function') return;
    if (e.target.closest('.smart-modal-window') ||
        e.target.closest('.os-window') ||
        e.target.closest('#console-window') ||
        e.target.closest('.os-context-menu') ||
        e.target.closest('#os-dock-container') ||
        e.target.closest('.suite-navbar') ||
        e.target.closest('.slide-drawer')) {
      return;
    }

    const iconEl = e.target.closest('.chassis-hero-box');
    if (iconEl) {
      e.preventDefault();
      // Ensure the background desktop context menu is closed
      hideDesktopContextMenu();

      let iconAppId = null;
      if (iconEl.id === 'management-desktop-icon') iconAppId = 'management';
      else if (iconEl.id === 'containers-desktop-icon') iconAppId = 'containers';
      else if (iconEl.id === 'vm-desktop-icon') iconAppId = 'vm';
      else if (iconEl.id === 'chassis-desktop-icon') iconAppId = 'console';
      else if (iconEl.id === 'fm-desktop-icon' || iconEl.id === 'rb-desktop-icon') iconAppId = 'fm';

      const openLabel = t('dock.open_app', 'Open');
      const nameEl = iconEl.querySelector('.icon-text');
      const iconName = nameEl ? (nameEl.innerText || nameEl.textContent || '').trim() : '';
      const isCustom = iconEl.classList.contains('custom-desktop-shortcut') || !!iconEl.dataset.shortcutId;

      ctxMenu.innerHTML = `
        <div class="ctx-item" id="ctx-open-app">
          <span style="font-size:var(--zn-fs-xs); margin-right:6px;">▶</span>
          <span>${escapeHtml(openLabel)}${iconName ? ` ${escapeHtml(iconName)}` : ''}</span>
        </div>
        ${iconAppId === 'fm' ? `
          <div class="ctx-item" id="ctx-new-window">
            <span style="font-size:var(--zn-fs-xs); margin-right:6px;">🪟</span>
            <span>${escapeHtml(t('dock.new_fm_window', 'New Window'))}</span>
          </div>
        ` : ''}
        <div style="height:1px; background:var(--zn-glaze-8); margin:4px 0;"></div>
        <div class="ctx-item" id="ctx-align-grid">📐 ${t('desktop.align_grid', 'Align to Grid')}</div>
        <div class="ctx-item" id="ctx-sort-name">🔤 ${t('desktop.sort_name', 'Sort by Name')}</div>
        ${isCustom ? `
          <div style="height:1px; background:var(--zn-glaze-8); margin:4px 0;"></div>
          <div class="ctx-item" id="ctx-remove-shortcut" style="color:var(--zn-text-crit);">
            <span style="font-size:var(--zn-fs-xs); margin-right:6px;">🗑️</span>
            <span>Remove from Desktop</span>
          </div>
        ` : ''}
      `;

      document.getElementById('ctx-open-app')?.addEventListener('click', (ev) => {
        ev.stopPropagation();
        hideMenu();
        if (iconAppId && KNOWN_APPS[iconAppId]?.launch) {
          KNOWN_APPS[iconAppId].launch();
        } else {
          iconEl.click();
        }
      });

      document.getElementById('ctx-new-window')?.addEventListener('click', (ev) => {
        ev.stopPropagation();
        hideMenu();
        if (typeof window.openNewFileManagerWindow === 'function') {
          window.openNewFileManagerWindow();
        }
      });

      if (isCustom) {
        document.getElementById('ctx-remove-shortcut')?.addEventListener('click', (ev) => {
          ev.stopPropagation();
          hideMenu();
          removeDesktopShortcut(iconEl.id);
        });
      }

      wireGridAndSort();
      wireHide();

      ctxMenu.style.display = 'block';
      const menuW = 190;
      const menuH = ctxMenu.offsetHeight || 100;
      const left = Math.max(10, Math.min(window.innerWidth - menuW - 10, e.pageX));
      const top = Math.max(10, Math.min(window.innerHeight - menuH - 20, e.pageY));
      ctxMenu.style.left = `${left}px`;
      ctxMenu.style.top = `${top}px`;
      return;
    }

    // Right-clicked on empty desktop space:
    // If the unified desktop context menu element is present in the DOM, let desktop-context-menu.js handle it!
    if (document.getElementById('desktop-context-menu')) {
      return;
    }

    // Fallback for tests/environments where #desktop-context-menu is not present:
    e.preventDefault();
    ctxMenu.innerHTML = `
      <div class="ctx-item" id="ctx-spotlight">
        <span style="font-size:var(--zn-fs-xs); margin-right:6px;">⚡</span>
        <span>Command Palette</span>
        <kbd style="margin-left:auto; font-size:var(--zn-fs-xs); opacity:0.6;">⌘K</kbd>
      </div>
      <div class="ctx-item" id="ctx-open-mc">
        <span style="font-size:var(--zn-fs-xs); margin-right:6px;">🖥️</span>
        <span>Mission Control</span>
      </div>
      <div class="ctx-item" id="ctx-open-fm">
        <span style="font-size:var(--zn-fs-xs); margin-right:6px;">📁</span>
        <span>File Explorer</span>
      </div>
      <div class="ctx-item" id="ctx-new-fm">
        <span style="font-size:var(--zn-fs-xs); margin-right:6px;">🪟</span>
        <span>${escapeHtml(t('dock.new_fm_window', 'New Window'))}</span>
      </div>
      <div class="ctx-item" id="ctx-add-widget">
        <span style="font-size:var(--zn-fs-xs); margin-right:6px;">🧩</span>
        <span>${escapeHtml(t('ctx.add_widget', 'Add Widget…'))}</span>
      </div>
      <div style="height:1px; background:var(--zn-glaze-8); margin:4px 0;"></div>
      <div class="ctx-item" id="ctx-align-grid">📐 ${t('desktop.align_grid', 'Align to Grid')}</div>
      <div class="ctx-item" id="ctx-sort-name">🔤 ${t('desktop.sort_name', 'Sort by Name')}</div>
      <div style="height:1px; background:var(--zn-glaze-8); margin:4px 0;"></div>
      <div class="ctx-item" id="ctx-refresh-telemetry">
        <span style="font-size:var(--zn-fs-xs); margin-right:6px;">🔄</span>
        <span>Refresh Desktop</span>
      </div>
    `;

    document.getElementById('ctx-spotlight')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      hideMenu();
      if (typeof openSpotlight === 'function') openSpotlight();
    });
    document.getElementById('ctx-add-widget')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      hideMenu();
      if (typeof window.openWidgetSettings === 'function') {
        window.openWidgetSettings();
      }
    });
    document.getElementById('ctx-open-mc')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      hideMenu();
      document.getElementById('management-desktop-icon')?.click();
    });
    document.getElementById('ctx-open-fm')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      hideMenu();
      document.getElementById('fm-desktop-icon')?.click();
    });
    document.getElementById('ctx-new-fm')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      hideMenu();
      if (typeof window.openNewFileManagerWindow === 'function') {
        window.openNewFileManagerWindow();
      }
    });
    document.getElementById('ctx-refresh-telemetry')?.addEventListener('click', (ev) => {
      ev.stopPropagation();
      hideMenu();
      window.location.reload();
    });

    wireGridAndSort();
    wireHide();
    ctxMenu.style.display = 'block';
    ctxMenu.style.left = `${e.pageX}px`;
    ctxMenu.style.top = `${e.pageY}px`;
  });

  const refreshIconPositions = () => {
    const isMobile = document.body.classList.contains('mobile-mode') || window.innerWidth <= 768;
    const allIcons = getAllIconElements();
    if (isMobile) {
      allIcons.forEach(({ el }) => {
        el.style.removeProperty('position');
        el.style.removeProperty('left');
        el.style.removeProperty('top');
      });
      return;
    }

    // 1. Reset if saved top is above Mission Control (e.g. 54 or 77)
    ['vm-desktop-icon', 'containers-desktop-icon'].forEach((k) => {
      const s = savedPositions[k];
      if (s && (s.top < 100 || s.top === 77)) {
        delete savedPositions[k];
      }
    });

    // 2. Legacy stack migration: In v1.7 before Containers was added, VM was at 189.
    // If VM was saved at old default (left: 24, top: 189):
    if (savedPositions['vm-desktop-icon'] && savedPositions['vm-desktop-icon'].left === 24 && savedPositions['vm-desktop-icon'].top === 189) {
      const cPos = savedPositions['containers-desktop-icon'];
      if (!cPos || (cPos.left === 24 && (cPos.top === 189 || cPos.top === 301))) {
        savedPositions['containers-desktop-icon'] = { left: 24, top: 189 };
        savedPositions['vm-desktop-icon'] = { left: 24, top: 301 };
      }
    }

    // 3. If Containers was saved at top: 301 (old collision where Containers overlapped File Explorer):
    if (savedPositions['containers-desktop-icon'] && savedPositions['containers-desktop-icon'].left === 24 && savedPositions['containers-desktop-icon'].top === 301) {
      savedPositions['containers-desktop-icon'] = { left: 24, top: 189 };
      if (!savedPositions['vm-desktop-icon'] || (savedPositions['vm-desktop-icon'].left === 24 && (savedPositions['vm-desktop-icon'].top === 189 || savedPositions['vm-desktop-icon'].top === 301))) {
        savedPositions['vm-desktop-icon'] = { left: 24, top: 301 };
      }
    }

    const placedIcons = [];
    let hasChanges = false;

    // Process all icons: default configs in order, then custom icons
    const processedIds = new Set();
    const iconsToProcess = [];

    defaultIconConfigs.forEach((cfg) => {
      const icon = allIcons.find((item) => item.id === cfg.id);
      if (icon) {
        iconsToProcess.push({ ...icon, defaultLeft: cfg.defaultLeft, defaultTop: cfg.defaultTop });
        processedIds.add(cfg.id);
      }
    });

    allIcons.forEach((icon) => {
      if (!processedIds.has(icon.id)) {
        iconsToProcess.push(icon);
      }
    });

    iconsToProcess.forEach(({ id, el, defaultLeft = 24, defaultTop = 77 }) => {
      const saved = savedPositions[id];
      const curLeft = (saved && typeof saved.left === 'number') ? saved.left : defaultLeft;
      const curTop = (saved && typeof saved.top === 'number') ? saved.top : defaultTop;

      const maxLeft = Math.max(24, window.innerWidth - (el.offsetWidth || 136) - 10);
      const maxTop = Math.max(77, window.innerHeight - (el.offsetHeight || 136) - 70);

      let clampedLeft = Math.max(24, Math.min(maxLeft, curLeft));
      let clampedTop = Math.max(77, Math.min(maxTop, curTop));

      // Automatic collision avoidance & resolution against already placed icons
      if (isPositionOccupied(clampedLeft, clampedTop, placedIcons, id)) {
        const freeSlot = findNextFreeSlot(clampedLeft, clampedTop, placedIcons, maxLeft, maxTop, id);
        clampedLeft = freeSlot.left;
        clampedTop = freeSlot.top;
      }

      placedIcons.push({ id, left: clampedLeft, top: clampedTop });
      el.style.position = 'fixed';
      el.style.left = `${clampedLeft}px`;
      el.style.top = `${clampedTop}px`;

      if (!saved || saved.left !== clampedLeft || saved.top !== clampedTop) {
        savedPositions[id] = { left: clampedLeft, top: clampedTop };
        hasChanges = true;
      }
    });

    if (hasChanges) {
      try {
        localStorage.setItem(storageKey, JSON.stringify(savedPositions));
      } catch (err) {
        console.error('Failed to update desktop icon positions after collision resolution', err);
      }
    }
  };
  window.refreshDesktopIconPositions = refreshIconPositions;

  // Apply initial positions
  refreshIconPositions();

  const makeIconDraggable = (el, id) => {
    if (!el || el._draggableBound) return;
    el._draggableBound = true;

    let startX = 0, startY = 0, initLeft = 0, initTop = 0;
    let didDrag = false;
    let dragThresholdPassed = false;

    const onMouseDown = (e) => {
      if (e.button !== 0) return;
      if (document.body.classList.contains('mobile-mode') || window.innerWidth <= 768) return;

      startX = e.clientX;
      startY = e.clientY;
      const rect = el.getBoundingClientRect();
      initLeft = rect.left;
      initTop = rect.top;
      didDrag = false;
      dragThresholdPassed = false;

      const onMouseMove = (mEvt) => {
        const dx = mEvt.clientX - startX;
        const dy = mEvt.clientY - startY;
        if (!dragThresholdPassed && Math.hypot(dx, dy) > 5) {
          dragThresholdPassed = true;
          didDrag = true;
          el.classList.add('dragging');
        }
        if (dragThresholdPassed) {
          mEvt.preventDefault();
          const curMaxLeft = Math.max(24, window.innerWidth - (el.offsetWidth || 136) - 10);
          const curMaxTop = Math.max(77, window.innerHeight - (el.offsetHeight || 136) - 70);
          const newLeft = Math.max(24, Math.min(curMaxLeft, initLeft + dx));
          const newTop = Math.max(77, Math.min(curMaxTop, initTop + dy));
          el.style.left = `${newLeft}px`;
          el.style.top = `${newTop}px`;
        }
      };

      const onMouseUp = () => {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);

        if (dragThresholdPassed) {
          el.classList.remove('dragging');
          const finalRect = el.getBoundingClientRect();
          let finalLeft = Math.round(finalRect.left);
          let finalTop = Math.round(finalRect.top);

          const maxLeft = Math.max(24, window.innerWidth - (el.offsetWidth || 136) - 10);
          const maxTop = Math.max(77, window.innerHeight - (el.offsetHeight || 136) - 70);
          finalLeft = Math.max(24, Math.min(maxLeft, finalLeft));
          finalTop = Math.max(77, Math.min(maxTop, finalTop));

          // Check if dropped position collides with any other visible icon
          const otherIcons = getAllIconElements().filter((item) => item.id !== id);
          const otherPositions = otherIcons.map((item) => {
            const r = item.el.getBoundingClientRect();
            return { id: item.id, left: Math.round(r.left), top: Math.round(r.top) };
          });

          if (isPositionOccupied(finalLeft, finalTop, otherPositions, id)) {
            const freeSlot = findNextFreeSlot(finalLeft, finalTop, otherPositions, maxLeft, maxTop, id);
            finalLeft = freeSlot.left;
            finalTop = freeSlot.top;
            el.style.left = `${finalLeft}px`;
            el.style.top = `${finalTop}px`;
          }

          savedPositions[id] = { left: finalLeft, top: finalTop };
          try {
            localStorage.setItem(storageKey, JSON.stringify(savedPositions));
          } catch (err) {
            console.error('Failed to save desktop icon position', err);
          }
          setTimeout(() => { didDrag = false; dragThresholdPassed = false; }, 60);
        }
      };

      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    };

    el.addEventListener('mousedown', onMouseDown);

    // Capture phase click interceptor to stop modal opening on drag drop
    el.addEventListener('click', (e) => {
      if (didDrag || dragThresholdPassed) {
        e.stopImmediatePropagation();
        e.preventDefault();
        didDrag = false;
        dragThresholdPassed = false;
      }
    }, true);
  };
  window.makeDesktopIconDraggable = makeIconDraggable;

  // Bind draggable to all existing desktop icons
  getAllIconElements().forEach(({ el, id }) => makeIconDraggable(el, id));

  window.addEventListener('resize', () => {
    refreshIconPositions();
    restoreWindowsAfterWiden();
  });

  initDesktopLasso();
  initSpotlight();
}
