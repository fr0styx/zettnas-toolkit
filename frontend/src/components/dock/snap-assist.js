// The snap-assist layouts offered on the maximise button.
// Part of dock.js, split out by ARC-5.

import { t } from '../../i18n.js';
import { applyWindowSnap } from './snap.js';
import { keyboardFocused } from './window-drag.js';

export function initSnapAssistFlyout() {
  if (typeof document === 'undefined') return;
  let flyout = document.getElementById('snap-assist-flyout');
  if (!flyout && document.body) {
    flyout = document.createElement('div');
    flyout.id = 'snap-assist-flyout';
    flyout.className = 'snap-assist-flyout';
    flyout.setAttribute('role', 'dialog');
    flyout.setAttribute('aria-label', 'Snap Layouts');
    flyout.setAttribute('aria-hidden', 'true');
    flyout.innerHTML = `
      <div class="snap-layout-title">Snap Layouts</div>
      <div class="snap-templates-grid">
        <div class="snap-card" title="${t('ui.split_screen_1_2', 'Split Screen (1/2)')}">
          <button class="snap-slot" data-snap="left" aria-label="${t('ui.snap_left_half', 'Snap Left Half')}"></button>
          <button class="snap-slot" data-snap="right" aria-label="${t('ui.snap_right_half', 'Snap Right Half')}"></button>
        </div>
        <div class="snap-card snap-card-quad" title="${t('ui.quarter_grid_1_4', 'Quarter Grid (1/4)')}">
          <button class="snap-slot" data-snap="top-left" aria-label="${t('ui.snap_top_left', 'Snap Top Left')}"></button>
          <button class="snap-slot" data-snap="top-right" aria-label="${t('ui.snap_top_right', 'Snap Top Right')}"></button>
          <button class="snap-slot" data-snap="bottom-left" aria-label="${t('ui.snap_bottom_left', 'Snap Bottom Left')}"></button>
          <button class="snap-slot" data-snap="bottom-right" aria-label="${t('ui.snap_bottom_right', 'Snap Bottom Right')}"></button>
        </div>
      </div>
    `;
    document.body.appendChild(flyout);
  }

  if (!flyout) return;

  let activeTargetWindow = null;
  let activeTargetWinId = null;
  let hideTimer = null;
  let showTimer = null;

  const showFlyout = (btn) => {
    clearTimeout(hideTimer);
    clearTimeout(showTimer);
    showTimer = setTimeout(() => {
      const win = btn.closest('.win-box, .modal-container, .chassis-front-panel, .mgmt-app-window, .file-manager-window, .smart-modal-window, .container-inspector-window') ||
                  btn.closest('[id$="-window"]');
      if (!win) return;
      activeTargetWindow = win;
      activeTargetWinId = win.id === 'file-manager-window' ? 'fm' :
                         (win.id === 'management-window' ? 'management' :
                         (win.id === 'console-window' ? 'console' :
                         (win.id === 'smart-modal-window' ? 'smart' : win.id)));

      const rect = btn.getBoundingClientRect();
      flyout.style.top = `${rect.bottom + 6}px`;
      flyout.style.left = `${Math.min(window.innerWidth - 230, Math.max(10, rect.left - 100))}px`;
      flyout.classList.add('visible');
      flyout.setAttribute('aria-hidden', 'false');
    }, 180);
  };

  const scheduleHide = () => {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      flyout.classList.remove('visible');
      flyout.setAttribute('aria-hidden', 'true');
    }, 220);
  };

  flyout.addEventListener('mouseenter', () => clearTimeout(hideTimer));
  flyout.addEventListener('mouseleave', scheduleHide);

  flyout.querySelectorAll('.snap-slot').forEach((slot) => {
    slot.addEventListener('click', (e) => {
      e.stopPropagation();
      const zone = slot.dataset.snap;
      if (zone && activeTargetWindow) {
        applyWindowSnap(activeTargetWindow, zone, activeTargetWinId);
      }
      flyout.classList.remove('visible');
      flyout.setAttribute('aria-hidden', 'true');
    });
  });

  const MAX_BTN_SELECTOR = '.win-btn.max-btn, #console-max, #management-max, #fb-max, #smart-modal-max, #copy-toast-max, #setup-wizard-max';
  const isMaxBtn = (el) => el && el.closest && el.closest(MAX_BTN_SELECTOR);

  // High-performance event delegation replaces full-body subtree MutationObserver
  if (document.body) {
    document.body.addEventListener('mouseover', (e) => {
      const btn = isMaxBtn(e.target);
      if (btn) showFlyout(btn);
    });
    document.body.addEventListener('mouseout', (e) => {
      const btn = isMaxBtn(e.target);
      if (btn) scheduleHide();
    });
    document.body.addEventListener('focusin', (e) => {
      const btn = isMaxBtn(e.target);
      if (btn) showFlyout(btn);
    });
    document.body.addEventListener('focusout', (e) => {
      const btn = isMaxBtn(e.target);
      if (btn) scheduleHide();
    });
  }

  const attachToMaxButtons = () => {
    const maxButtons = document.querySelectorAll(MAX_BTN_SELECTOR);
    maxButtons.forEach((btn) => {
      if (btn._snapAssistBound) return;
      btn._snapAssistBound = true;
      btn.addEventListener('mouseenter', () => showFlyout(btn));
      btn.addEventListener('mouseleave', scheduleHide);
      btn.addEventListener('focus', () => keyboardFocused(btn) && showFlyout(btn));
      btn.addEventListener('blur', scheduleHide);
    });
  };

  attachToMaxButtons();

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && flyout.classList.contains('visible')) {
      flyout.classList.remove('visible');
      flyout.setAttribute('aria-hidden', 'true');
    }
  });
}
