// The top bar's user pill and profile menu.
// Part of dock.js, split out by ARC-5.

import { ZettEventBus } from '../../event-bus.js';

export function initTopbarUserPill() {
  const topbarPill = document.getElementById('topbar-user-pill');
  if (!topbarPill || topbarPill.dataset.userPillBound === 'true') return;
  topbarPill.dataset.userPillBound = 'true';

  topbarPill.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleUserProfileFlyout(topbarPill);
  });

  topbarPill.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      e.stopPropagation();
      toggleUserProfileFlyout(topbarPill);
    }
  });
}

export function toggleUserProfileFlyout(anchorEl) {
  let flyout = document.getElementById('user-profile-flyout');
  if (!flyout) {
    flyout = document.createElement('div');
    flyout.id = 'user-profile-flyout';
    flyout.className = 'user-profile-flyout glassmorphic-panel';
    flyout.innerHTML = `
      <div class="user-flyout-header" style="display:flex; align-items:center; gap:12px; padding:16px; border-bottom:1px solid var(--zn-line-8);">
        <div id="user-flyout-avatar" style="width:42px; height:42px; border-radius:50%; background:linear-gradient(135deg, #0284c7, #0369a1); display:flex; align-items:center; justify-content:center; font-weight:800; color:#fff; font-size:16px; border:1px solid var(--lt-r-ffffff4c, rgba(255,255,255,0.3)); box-shadow:0 4px 12px rgba(2,132,199,0.3);">
          A
        </div>
        <div style="flex:1; min-width:0;">
          <div id="user-flyout-name" style="font-weight:700; color:var(--zn-text-strong); font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">Administrator</div>
          <div id="user-flyout-username" style="font-size:var(--zn-fs-xs); color:var(--muted);">@admin</div>
          <span id="user-flyout-role" style="font-size:var(--zn-fs-xs); font-weight:700; color:var(--lt-ink-brand, var(--accent-cyan, #38bdf8)); background:rgba(56,189,248,0.12); padding:2px 6px; border-radius:4px; display:inline-block; margin-top:4px;">SuperAdmin 👑</span>
        </div>
      </div>
      <div class="user-flyout-actions" style="padding:8px;">
        <button class="user-flyout-btn" id="btn-flyout-lock" style="width:100%; display:flex; align-items:center; gap:10px; padding:9px 12px; background:transparent; border:none; border-radius:6px; color:var(--zn-text-strong); font-size:13px; font-weight:600; cursor:pointer; text-align:left; transition:background 0.15s ease;">
          <span style="font-size:15px;">🔒</span> <span>Lock Screen</span>
          <span style="margin-left:auto; font-size:var(--zn-fs-xs); color:var(--muted); font-family:monospace;">Cmd+L</span>
        </button>
        <button class="user-flyout-btn" id="btn-flyout-users" style="width:100%; display:flex; align-items:center; gap:10px; padding:9px 12px; background:transparent; border:none; border-radius:6px; color:var(--zn-text-strong); font-size:13px; font-weight:600; cursor:pointer; text-align:left; transition:background 0.15s ease;">
          <span style="font-size:15px;">👥</span> <span>Users & Permissions</span>
        </button>
        <button class="user-flyout-btn" id="btn-flyout-security" style="width:100%; display:flex; align-items:center; gap:10px; padding:9px 12px; background:transparent; border:none; border-radius:6px; color:var(--zn-text-strong); font-size:13px; font-weight:600; cursor:pointer; text-align:left; transition:background 0.15s ease;">
          <span style="font-size:15px;">🛡️</span> <span>Account Security & 2FA</span>
        </button>
        <div style="height:1px; background:var(--zn-glaze-6); margin:6px 0;"></div>
        <button class="user-flyout-btn" id="btn-flyout-switch" style="width:100%; display:flex; align-items:center; gap:10px; padding:9px 12px; background:transparent; border:none; border-radius:6px; color:var(--zn-text-soft); font-size:13px; font-weight:600; cursor:pointer; text-align:left; transition:background 0.15s ease;">
          <span style="font-size:15px;">🔄</span> <span>Switch User</span>
        </button>
        <button class="user-flyout-btn" id="btn-flyout-logout" style="width:100%; display:flex; align-items:center; gap:10px; padding:9px 12px; background:transparent; border:none; border-radius:6px; color:var(--crit, #ff6b6b); font-size:13px; font-weight:600; cursor:pointer; text-align:left; transition:background 0.15s ease;">
          <span style="font-size:15px;">🚪</span> <span>Sign Out</span>
        </button>
      </div>
    `;
    document.body.appendChild(flyout);

    // Hover effect for buttons
    flyout.querySelectorAll('.user-flyout-btn').forEach((btn) => {
      btn.addEventListener('mouseenter', () => { btn.style.background = 'rgba(255,255,255,0.08)'; });
      btn.addEventListener('mouseleave', () => { btn.style.background = 'transparent'; });
    });

    const resetFlyoutTrigger = () => {
      if (anchorEl) {
        anchorEl.setAttribute('aria-expanded', 'false');
        anchorEl.classList.remove('active');
      }
      const topbarPill = document.getElementById('topbar-user-pill');
      if (topbarPill) {
        topbarPill.setAttribute('aria-expanded', 'false');
        topbarPill.classList.remove('active');
      }
    };

    // Actions
    document.getElementById('btn-flyout-lock').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      import('../auth.js').then((m) => m.lockDesktop());
    });

    const openMgmtPane = (pane, subtab = null) => {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow(pane, null, subtab);
      } else {
        import('../management.js').then((m) => {
          if (typeof m.initManagement === 'function') m.initManagement();
          if (typeof window.openManagementWindow === 'function') {
            window.openManagementWindow(pane, null, subtab);
          } else {
            document.getElementById('management-desktop-icon')?.click();
          }
        }).catch(() => {
          document.getElementById('management-desktop-icon')?.click();
        });
      }
      ZettEventBus.emit('window:open', { id: 'management', pane: pane, subtab: subtab });
    };

    document.getElementById('btn-flyout-users').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      openMgmtPane('mgmt-pane-users', 'users-pane-list');
    });

    document.getElementById('btn-flyout-security').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      openMgmtPane('mgmt-pane-users', 'users-pane-2fa');
    });

    document.getElementById('btn-flyout-switch').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      import('../auth.js').then((m) => m.switchUser());
    });

    document.getElementById('btn-flyout-logout').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      import('../auth.js').then((m) => m.logout());
    });

    // Click outside to close
    document.addEventListener('click', (evt) => {
      if (flyout.style.display !== 'none' && !flyout.contains(evt.target)) {
        const topbarPill = document.getElementById('topbar-user-pill');
        if ((!anchorEl || !anchorEl.contains(evt.target)) && (!topbarPill || !topbarPill.contains(evt.target))) {
          flyout.style.display = 'none';
          resetFlyoutTrigger();
        }
      }
    });

    document.addEventListener('keydown', (evt) => {
      if (evt.key === 'Escape' && flyout.style.display === 'block') {
        flyout.style.display = 'none';
        resetFlyoutTrigger();
      }
    });
  }

  // Toggle display
  if (flyout.style.display === 'block') {
    flyout.style.display = 'none';
    if (anchorEl) {
      anchorEl.setAttribute('aria-expanded', 'false');
      anchorEl.classList.remove('active');
    }
    const topbarPill = document.getElementById('topbar-user-pill');
    if (topbarPill) {
      topbarPill.setAttribute('aria-expanded', 'false');
      topbarPill.classList.remove('active');
    }
    return;
  }

  // Refresh current user info
  import('../users.js').then((m) => m.updateUserInterfaceElements());

  const rect = anchorEl ? anchorEl.getBoundingClientRect() : { top: 0, bottom: 48, left: 16, width: 30 };
  const flyoutW = 250;
  const isTopBar = rect.top < (typeof window !== 'undefined' ? window.innerHeight / 2 : 400);

  if (isTopBar) {
    const topPos = rect.bottom + 8;
    const leftPos = Math.max(12, Math.min((typeof window !== 'undefined' ? window.innerWidth : 1200) - flyoutW - 12, rect.left));
    flyout.style.position = 'fixed';
    flyout.style.top = `${topPos}px`;
    flyout.style.bottom = 'auto';
    flyout.style.left = `${leftPos}px`;
    flyout.style.animation = 'flyoutSlideDown 0.18s cubic-bezier(0.16, 1, 0.3, 1)';
  } else {
    const bottomPos = (typeof window !== 'undefined' ? window.innerHeight : 900) - rect.top + 12;
    const leftPos = Math.max(16, Math.min((typeof window !== 'undefined' ? window.innerWidth : 1200) - flyoutW - 16, rect.left + (rect.width / 2) - (flyoutW / 2)));
    flyout.style.position = 'fixed';
    flyout.style.top = 'auto';
    flyout.style.bottom = `${bottomPos}px`;
    flyout.style.left = `${leftPos}px`;
    flyout.style.animation = 'flyoutSlideUp 0.18s cubic-bezier(0.16, 1, 0.3, 1)';
  }

  flyout.style.width = `${flyoutW}px`;
  flyout.style.zIndex = '99999';
  flyout.style.display = 'block';

  if (anchorEl) {
    anchorEl.setAttribute('aria-expanded', 'true');
    anchorEl.classList.add('active');
  }
}
