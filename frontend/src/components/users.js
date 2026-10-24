/**
 * ZettNAS Toolkit - Multi-User Identity, RBAC & Two-Factor Authentication Component
 * Handles User inventory, Role assignment, Session revocation, and TOTP 2FA setup.
 */

import { onManagementDom } from '../management-dom.js';
import { auth, apiFetch, setSessionUserProvider } from '../api.js';
import { escapeHtml, trapFocus, copyText } from '../utils.js';
import { ZettEventBus } from '../event-bus.js';
import { t } from '../i18n.js';
import { showToast, showConfirmToast, showPromptToast } from '../toast.js';
import { initTopbarUserPill } from './dock.js';
import { openShareAccessModal } from './share-access.js';

import { formatDateTime } from '../format.js';
import { renderInvites } from './invites.js';
import { emptyRowHtml } from './empty-state.js';
let _currentUser = null;

export function setCurrentUser(user) {
  _currentUser = user;
  updateUserInterfaceElements();
}

setSessionUserProvider(() => _currentUser?.username || null);

export function getCurrentUser() {
  return _currentUser;
}

export async function fetchCurrentProfile() {
  try {
    const res = await apiFetch('/api/auth/me', { credentials: 'include' });
    if (res.ok) {
      const data = await res.json();
      setCurrentUser(data);
      return data;
    }
  } catch (err) {
    console.warn('[USERS] Could not fetch current user profile:', err);
  }
  return null;
}

export function updateUserInterfaceElements() {
  if (!_currentUser) return;
  const username = _currentUser.username || 'admin';
  const displayName = _currentUser.display_name || username;
  const roleId = _currentUser.role_id || 'share_user';
  const avatarLetter = (displayName[0] || username[0] || 'U').toUpperCase();

  // Update Topbar User Pill
  const topbarAvatar = document.getElementById('topbar-user-avatar-initial');
  if (topbarAvatar) topbarAvatar.textContent = avatarLetter;
  const topbarName = document.getElementById('topbar-user-display-name');
  if (topbarName) topbarName.textContent = displayName;

  // Update Dock User Pill (backward compatibility)
  const dockAvatar = document.getElementById('dock-user-avatar-initial');
  if (dockAvatar) dockAvatar.textContent = avatarLetter;
  const dockName = document.getElementById('dock-user-display-name');
  if (dockName) dockName.textContent = displayName;

  // Update Lock Overlay
  const lockAvatar = document.getElementById('lock-avatar');
  if (lockAvatar) lockAvatar.textContent = avatarLetter;
  const lockName = document.getElementById('lock-display-name');
  if (lockName) lockName.textContent = displayName;
  const lockRole = document.getElementById('lock-role-badge');
  if (lockRole) lockRole.textContent = formatRole(roleId);

  // Update User Flyout
  const flyoutAvatar = document.getElementById('user-flyout-avatar');
  if (flyoutAvatar) flyoutAvatar.textContent = avatarLetter;
  const flyoutName = document.getElementById('user-flyout-name');
  if (flyoutName) flyoutName.textContent = displayName;
  const flyoutUser = document.getElementById('user-flyout-username');
  if (flyoutUser) flyoutUser.textContent = `@${username}`;
  const flyoutRole = document.getElementById('user-flyout-role');
  if (flyoutRole) flyoutRole.textContent = formatRole(roleId);

  // Dynamic privilege gating: hide Users tab for non-admins
  const usersTab = document.getElementById('mgmt-tab-users');
  if (usersTab) {
    const isAdmin = ['superadmin', 'storage_admin'].includes(roleId) ||
                    (_currentUser.scopes && (_currentUser.scopes.includes('*') || _currentUser.scopes.includes('users:read')));
    usersTab.style.display = isAdmin ? '' : 'none';
  }
}

export function openModal(modal) {
  if (!modal) return;
  modal.classList.add('open');
  modal.style.display = 'flex';
  if (modal._unbindFocusTrap) {
    try { modal._unbindFocusTrap(); } catch (_) {}
    modal._unbindFocusTrap = null;
  }
  const modalWin = modal.querySelector('.modal-window, .mgmt-modal-window, .smart-modal-window') || modal;
  modal._unbindFocusTrap = trapFocus(modalWin, () => closeModal(modal));
  const firstInput = modal.querySelector('input:not([disabled]), select:not([disabled]), button:not([disabled])');
  if (firstInput) setTimeout(() => firstInput.focus(), 50);
}

export function closeModal(modal) {
  if (!modal) return;
  if (modal._unbindFocusTrap) {
    try { modal._unbindFocusTrap(); } catch (_) {}
    modal._unbindFocusTrap = null;
  }
  modal.classList.remove('open');
  modal.style.display = 'none';
}

let _usersCache = {};

export function formatRole(roleId) {
  const map = {
    superadmin: 'SuperAdmin 👑',
    storage_admin: 'Storage Admin 💾',
    app_operator: 'App Operator 📦',
    backup_operator: 'Backup Operator 🔄',
    share_user: 'Family & Share User 👤',
    auditor: 'Auditor & Viewer 👁️'
  };
  return map[roleId] || roleId;
}

export function initUsersManagement() {
  initTopbarUserPill();
  fetchCurrentProfile();
  onManagementDom(bindUsersPane);
  bindUserModals();
}

// The Users pane lives in Mission Control, which is inserted when first needed (FE-04)
function bindUsersPane() {
  // Sub-tabs in Users Pane
  const subtabs = document.querySelectorAll('.users-nav-btn');
  subtabs.forEach((btn) => {
    btn.onclick = () => {
      switchUsersSubtab(btn.dataset.tab);
    };
  });

  // Modal triggers
  const btnAddUser = document.getElementById('btn-add-user');
  if (btnAddUser) btnAddUser.onclick = showAddUserModal;

  const btnRefreshUsers = document.getElementById('btn-refresh-users');
  if (btnRefreshUsers) btnRefreshUsers.onclick = loadUsersList;

  const btnShareAccess = document.getElementById('btn-share-access');
  if (btnShareAccess) btnShareAccess.onclick = openShareAccessModal;

  const btnRefreshSessions = document.getElementById('btn-refresh-sessions');
  if (btnRefreshSessions) btnRefreshSessions.onclick = loadSessionsList;

  const btnRevokeAllSessions = document.getElementById('btn-revoke-all-sessions');
  if (btnRevokeAllSessions) btnRevokeAllSessions.onclick = revokeAllOtherSessions;

  const btnEnable2fa = document.getElementById('btn-enable-2fa');
  if (btnEnable2fa) btnEnable2fa.onclick = start2FASetup;

  const btnDisable2fa = document.getElementById('btn-disable-2fa');
  if (btnDisable2fa) btnDisable2fa.onclick = disable2FA;

  const btnJumpToSecurity = document.getElementById('btn-jump-to-security');
  if (btnJumpToSecurity && !btnJumpToSecurity.dataset.bound) {
    btnJumpToSecurity.dataset.bound = 'true';
    btnJumpToSecurity.onclick = () => {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-pane-security');
      }
    };
  }

  const btnJumpTo2fa = document.getElementById('btn-jump-to-2fa');
  if (btnJumpTo2fa && !btnJumpTo2fa.dataset.bound) {
    btnJumpTo2fa.dataset.bound = 'true';
    btnJumpTo2fa.onclick = () => {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-pane-users', null, 'users-pane-2fa');
      }
    };
  }

}

function bindUserModals() {
  // Close modals via buttons
  document.querySelectorAll('.modal-close-btn').forEach((btn) => {
    btn.onclick = (e) => {
      const modal = e.target.closest('.smart-modal-backdrop') || e.target.closest('.os-modal');
      if (modal) closeModal(modal);
    };
  });

  // Close modals on clicking outer backdrop
  ['modal-add-user', 'modal-edit-user', 'modal-reset-password', 'modal-setup-2fa'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.onclick = (e) => {
        if (e.target === el) closeModal(el);
      };
    }
  });

  // Escape key closes open user modals
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      ['modal-add-user', 'modal-edit-user', 'modal-reset-password', 'modal-setup-2fa'].forEach((id) => {
        const el = document.getElementById(id);
        if (el && el.classList.contains('open')) closeModal(el);
      });
    }
  });
}

export function switchUsersSubtab(targetId) {
  const subtabs = document.querySelectorAll('.users-nav-btn');
  subtabs.forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === targetId);
  });
  document.querySelectorAll('.users-subpane').forEach((pane) => {
    pane.style.display = pane.id === targetId ? 'block' : 'none';
  });
  if (targetId === 'users-pane-list') loadUsersList();
  if (targetId === 'users-pane-sessions') loadSessionsList();
  if (targetId === 'users-pane-2fa') load2FAStatus();
}

export async function loadUsersPane(defaultSubtab = 'users-pane-list') {
  initUsersManagement();
  await fetchCurrentProfile();
  switchUsersSubtab(defaultSubtab);
}

export async function loadUsersList() {
  const container = document.getElementById('users-table-body');
  if (!container) return;
  container.innerHTML = '<tr><td colspan="7" style="text-align:center; padding: 24px; color: var(--muted);">Loading users...</td></tr>';

  try {
    const res = await apiFetch('/api/users', { credentials: 'include' });
    if (!res.ok) {
      if (res.status === 403) {
        container.innerHTML = '<tr><td colspan="7" style="text-align:center; padding: 24px; color: var(--crit);">Requires SuperAdmin or users:read permission.</td></tr>';
        return;
      }
      throw new Error(`Server returned ${res.status}`);
    }
    const data = await res.json();
    const users = data.users || [];

    renderInvites(document.getElementById('invites-mount'));
    if (users.length === 0) {
      container.innerHTML = emptyRowHtml(7, {
        title: t('users.none_title', 'Only you so far'),
        body: t('users.none_desc', 'Give each person in the house their own sign-in, so their files and access are their own.'),
        action: { target: 'btn-add-user', label: t('users.add', 'Add a person') },
      });
      return;
    }

    _usersCache = {};
    users.forEach((u) => {
      _usersCache[u.id] = u;
    });

    container.innerHTML = users.map((u) => {
      const letter = (u.display_name?.[0] || u.username?.[0] || 'U').toUpperCase();
      const isActive = u.status === 'active';
      const isMfa = !!u.mfa_enabled;
      const isSelf = _currentUser && _currentUser.id === u.id;
      const quotaStr = u.storage_quota_bytes > 0
        ? `${Math.round(u.storage_quota_bytes / (1024 * 1024 * 1024))} GB`
        : 'Unlimited';

      return `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.06); transition: background 0.15s ease;">
          <td style="padding: 12px; display:flex; align-items:center; gap: 10px;">
            <div style="width: 32px; height: 32px; border-radius: 50%; background: linear-gradient(135deg, #0284c7, #0369a1); display:flex; align-items:center; justify-content:center; font-weight:800; color:#fff; font-size: var(--zn-fs-sm); border: 1px solid rgba(255,255,255,0.2);">
              ${escapeHtml(letter)}
            </div>
            <div>
              <div style="font-weight:700; color:#fff; font-size: var(--zn-fs-sm);">${escapeHtml(u.display_name || u.username)} ${isSelf ? '<span style="font-size: var(--zn-fs-xs); background:rgba(14,165,233,0.2); color:#38bdf8; padding:2px 6px; border-radius:4px; margin-left:4px;">YOU</span>' : ''}</div>
              <div style="font-size: var(--zn-fs-xs); color:var(--muted);">@${escapeHtml(u.username)}</div>
            </div>
          </td>
          <td style="padding: 12px; font-size: var(--zn-fs-sm); color:#cbd5e1;">${escapeHtml(u.email || '--')}</td>
          <td style="padding: 12px;">
            <span style="font-size: var(--zn-fs-xs); font-weight: 700; padding: 3px 8px; border-radius: 6px; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12); color:#fff;">
              ${escapeHtml(formatRole(u.role_id))}
            </span>
          </td>
          <td style="padding: 12px;">
            <span style="font-size: var(--zn-fs-xs); font-weight: 700; padding: 2px 7px; border-radius: 4px; background: ${isActive ? 'rgba(37,194,160,0.15)' : 'rgba(239,68,68,0.15)'}; color: ${isActive ? 'var(--ok2)' : 'var(--crit)'}; border: 1px solid ${isActive ? 'rgba(37,194,160,0.3)' : 'rgba(239,68,68,0.3)'};">
              ${isActive ? 'ACTIVE' : 'DISABLED'}
            </span>
          </td>
          <td style="padding: 12px;">
            <span style="font-size: var(--zn-fs-xs); display:inline-flex; align-items:center; gap: 4px; color: ${isMfa ? 'var(--ok2)' : 'var(--muted)'};">
              ${isMfa ? '🛡️ Enabled' : '⚪ Off'}
            </span>
          </td>
          <td style="padding: 12px; font-size: var(--zn-fs-sm); color: #94a3b8;">${quotaStr}</td>
          <td style="padding: 12px; text-align:right;">
            <div style="display:inline-flex; gap: 6px;">
              <button class="suite-toolkit-btn sm btn-edit-user" data-id="${u.id}" title="${t('ui.edit_user', 'Edit User')}">✏️</button>
              <button class="suite-toolkit-btn sm btn-pwd-user" data-id="${u.id}" data-user="${escapeHtml(u.username)}" title="${t('ui.reset_password', 'Reset Password')}">🔑</button>
              ${!isSelf ? `
                <button class="suite-toolkit-btn sm btn-toggle-user" data-id="${u.id}" data-status="${u.status}" title="${isActive ? 'Disable User' : 'Enable User'}">
                  ${isActive ? '🚫' : '✅'}
                </button>
                <button class="suite-toolkit-btn sm danger btn-delete-user" data-id="${u.id}" data-user="${escapeHtml(u.username)}" title="${t('ui.delete_user', 'Delete User')}">🗑️</button>
              ` : ''}
            </div>
          </td>
        </tr>
      `;
    }).join('');

    // Attach row events
    container.querySelectorAll('.btn-edit-user').forEach((btn) => {
      btn.onclick = () => {
        const u = _usersCache[btn.dataset.id];
        if (u) showEditUserModal(u);
      };
    });

    container.querySelectorAll('.btn-pwd-user').forEach((btn) => {
      btn.onclick = () => {
        showResetPasswordModal(btn.dataset.id, btn.dataset.user);
      };
    });

    container.querySelectorAll('.btn-toggle-user').forEach((btn) => {
      btn.onclick = async () => {
        const uid = btn.dataset.id;
        const curStatus = btn.dataset.status;
        const newStatus = curStatus === 'active' ? 'disabled' : 'active';
        await toggleUserStatus(uid, newStatus);
      };
    });

    container.querySelectorAll('.btn-delete-user').forEach((btn) => {
      btn.onclick = () => {
        confirmDeleteUser(btn.dataset.id, btn.dataset.user);
      };
    });

  } catch (err) {
    container.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 24px; color: var(--crit);">Failed to load users: ${escapeHtml(err.message)}</td></tr>`;
  }
}

export function showAddUserModal() {
  const modal = document.getElementById('modal-add-user');
  if (!modal) return;
  openModal(modal);
  const form = document.getElementById('form-add-user');
  if (form) {
    form.reset();
    form.onsubmit = async (e) => {
      e.preventDefault();
      const username = document.getElementById('add-user-username').value.trim();
      const displayName = document.getElementById('add-user-display').value.trim();
      const email = document.getElementById('add-user-email').value.trim();
      const password = document.getElementById('add-user-password').value;
      const roleId = document.getElementById('add-user-role').value;
      const quotaGb = parseInt(document.getElementById('add-user-quota').value || '0', 10);

      const submitBtn = form.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      submitBtn.textContent = 'CREATING...';

      try {
        const res = await apiFetch('/api/users', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            username,
            display_name: displayName || username,
            email,
            password,
            role_id: roleId,
            storage_quota_bytes: quotaGb > 0 ? quotaGb * 1024 * 1024 * 1024 : 0
          })
        });
        const result = await res.json();
        if (res.ok) {
          closeModal(modal);
          loadUsersList();
          showToast(t('toast.user_created_successfully', 'User created successfully.'), 'success');
        } else {
          showToast(t('toast.error', 'Error: {detail}', { detail: result.detail || result.error || 'Failed to create user' }), 'error');
        }
      } catch (err) {
        showToast(t('toast.request_failed', 'Request failed: {error}', { error: err.message }), 'error');
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'CREATE USER';
      }
    };
  }
}

export function showEditUserModal(user) {
  const modal = document.getElementById('modal-edit-user');
  if (!modal) return;
  openModal(modal);

  document.getElementById('edit-user-id').value = user.id;
  document.getElementById('edit-user-username').value = user.username;
  document.getElementById('edit-user-display').value = user.display_name || '';
  document.getElementById('edit-user-email').value = user.email || '';
  document.getElementById('edit-user-role').value = user.role_id;
  const quotaGb = user.storage_quota_bytes > 0 ? Math.round(user.storage_quota_bytes / (1024 * 1024 * 1024)) : 0;
  document.getElementById('edit-user-quota').value = quotaGb || '';

  const form = document.getElementById('form-edit-user');
  if (form) {
    form.onsubmit = async (e) => {
      e.preventDefault();
      const displayName = document.getElementById('edit-user-display').value.trim();
      const email = document.getElementById('edit-user-email').value.trim();
      const roleId = document.getElementById('edit-user-role').value;
      const qVal = parseInt(document.getElementById('edit-user-quota').value || '0', 10);

      const submitBtn = form.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      submitBtn.textContent = t('setup.saving', 'SAVING...');

      try {
        const res = await apiFetch(`/api/users/${user.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            display_name: displayName,
            email,
            role_id: roleId,
            storage_quota_bytes: qVal > 0 ? qVal * 1024 * 1024 * 1024 : 0
          })
        });
        if (res.ok) {
          closeModal(modal);
          loadUsersList();
          fetchCurrentProfile();
          showToast(t('toast.user_updated_successfully', 'User updated successfully.'), 'success');
        } else {
          const err = await res.json();
          showToast(t('toast.error', 'Error: {detail}', { detail: err.detail || 'Failed to update user' }), 'error');
        }
      } catch (err) {
        showToast(t('toast.request_failed', 'Request failed: {error}', { error: err.message }), 'error');
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'SAVE CHANGES';
      }
    };
  }
}

export function showResetPasswordModal(userId, username) {
  const modal = document.getElementById('modal-reset-password');
  if (!modal) return;
  openModal(modal);
  document.getElementById('reset-pwd-username').textContent = `@${username}`;

  const form = document.getElementById('form-reset-password');
  // Changing your own password needs the current one (SEC-13).
  const isSelf = !!_currentUser && _currentUser.id === userId;
  const currentWrap = document.getElementById('reset-pwd-current-wrap');
  const currentInput = document.getElementById('reset-pwd-current');
  if (currentWrap) currentWrap.style.display = isSelf ? '' : 'none';
  if (currentInput) currentInput.required = isSelf;
  if (form) {
    form.reset();
    form.onsubmit = async (e) => {
      e.preventDefault();
      const newPassword = document.getElementById('reset-pwd-input').value;
      const confirmPassword = document.getElementById('reset-pwd-confirm').value;

      if (newPassword !== confirmPassword) {
        showToast(t('toast.passwords_do_not_match', 'Passwords do not match.'), 'error');
        return;
      }

      const submitBtn = form.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      submitBtn.textContent = 'UPDATING...';

      try {
        const res = await apiFetch(`/api/users/${userId}/password`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(
            isSelf
              ? { new_password: newPassword, current_password: currentInput?.value || '' }
              : { new_password: newPassword }
          )
        });
        if (res.ok) {
          showToast(isSelf ? 'Password updated. Your other sessions were signed out.' : 'Password updated. That user was signed out everywhere.', 'success');
          closeModal(modal);
        } else {
          const err = await res.json();
          showToast(t('toast.error', 'Error: {detail}', { detail: err.detail || 'Failed to reset password' }), 'error');
        }
      } catch (err) {
        showToast(t('toast.request_failed', 'Request failed: {error}', { error: err.message }), 'error');
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'UPDATE PASSWORD';
      }
    };
  }
}

async function toggleUserStatus(userId, newStatus) {
  try {
    const res = await apiFetch(`/api/users/${userId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ status: newStatus })
    });
    if (res.ok) {
      loadUsersList();
      showToast(t('toast.user_status_updated', 'User status updated.'), 'success');
    } else {
      const err = await res.json();
      showToast(t('toast.could_not_change_status', 'Could not change status: {detail}', { detail: err.detail || 'Error' }), 'error');
    }
  } catch (err) {
    showToast(t('toast.request_failed', 'Request failed: {error}', { error: err.message }), 'error');
  }
}

export function confirmDeleteUser(userId, username) {
  showConfirmToast(
    'Delete User',
    `Are you sure you want to permanently delete user @${username}? This will remove their account and revoke all sessions.`,
    async () => {
      try {
        const res = await apiFetch(`/api/users/${userId}`, {
          method: 'DELETE',
          confirmed: true,
          credentials: 'include'
        });
        if (res.ok) {
          loadUsersList();
          showToast(t('toast.user_deleted_2', 'User @{username} deleted.', { username: username }), 'success');
        } else {
          const err = await res.json();
          showToast(t('toast.could_not_delete_user', 'Could not delete user: {detail}', { detail: err.detail || 'Error' }), 'error');
        }
      } catch (err) {
        showToast(t('toast.request_failed', 'Request failed: {error}', { error: err.message }), 'error');
      }
    },
    null,
    { okText: 'Delete User', cancelText: 'Cancel' }
  );
}

export async function loadSessionsList() {
  const container = document.getElementById('sessions-table-body');
  if (!container) return;
  container.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 24px; color: var(--muted);">Loading sessions...</td></tr>';

  try {
    const res = await apiFetch('/api/auth/sessions', { credentials: 'include' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const sessions = data.sessions || [];

    if (sessions.length === 0) {
      container.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 24px; color: var(--muted);">No active sessions found.</td></tr>';
      return;
    }

    container.innerHTML = sessions.map((s) => {
      const createdStr = formatDateTime(s.created_at);
      const lastStr = formatDateTime(s.last_active_at);
      const isCurrent = !!s.is_current;

      return `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.06);">
          <td style="padding: 12px; font-weight:700; color:#fff;">
            ${isCurrent ? '💻 Current Browser' : '🌐 Remote Device'}
            ${isCurrent ? '<span style="font-size: var(--zn-fs-xs); background:rgba(37,194,160,0.2); color:var(--ok2); padding:2px 6px; border-radius:4px; margin-left:6px;">THIS DEVICE</span>' : ''}
            <div style="font-size: var(--zn-fs-xs); font-weight:normal; color:var(--muted); margin-top:2px;">${escapeHtml(s.user_agent || 'Unknown Browser')}</div>
          </td>
          <td style="padding: 12px; font-size: var(--zn-fs-sm); color:#cbd5e1; font-family:monospace;">${escapeHtml(s.ip_address || '127.0.0.1')}</td>
          <td style="padding: 12px; font-size: var(--zn-fs-sm); color:#94a3b8;">${createdStr}</td>
          <td style="padding: 12px; font-size: var(--zn-fs-sm); color:#94a3b8;">${lastStr}</td>
          <td style="padding: 12px; text-align:right;">
            ${!isCurrent ? `
              <button class="suite-toolkit-btn sm danger btn-revoke-session" data-id="${s.id}">Revoke</button>
            ` : '<span style="font-size: var(--zn-fs-xs); color:var(--muted);">Active</span>'}
          </td>
        </tr>
      `;
    }).join('');

    container.querySelectorAll('.btn-revoke-session').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const sid = btn.dataset.id;
        await apiFetch(`/api/auth/sessions/${sid}`, { method: 'DELETE', credentials: 'include' });
        loadSessionsList();
      });
    });

  } catch (err) {
    container.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 24px; color: var(--crit);">Failed to load sessions: ${escapeHtml(err.message)}</td></tr>`;
  }
}

export function revokeAllOtherSessions() {
  showConfirmToast(
    'Revoke Other Sessions',
    'Revoke all other login sessions on other devices and browsers?',
    async () => {
      try {
        const res = await apiFetch('/api/auth/sessions', { method: 'DELETE', credentials: 'include' });
        if (res.ok) {
          showToast(t('toast.all_other_sessions_revoked', 'All other sessions revoked.'), 'success');
          loadSessionsList();
        } else {
          showToast(t('toast.failed_to_revoke_other_sessions', 'Failed to revoke other sessions.'), 'error');
        }
      } catch (err) {
        showToast(t('toast.failed', 'Failed: {error}', { error: err.message }), 'error');
      }
    },
    null,
    { okText: 'Revoke Sessions', cancelText: 'Cancel' }
  );
}

export async function load2FAStatus() {
  const statusContainer = document.getElementById('mfa-status-card');
  if (!statusContainer) return;

  try {
    const res = await apiFetch('/api/auth/mfa/status', { credentials: 'include' });
    if (!res.ok) return;
    const data = await res.json();
    const isEnabled = !!data.mfa_enabled;

    const btnEnable = document.getElementById('btn-enable-2fa');
    const btnDisable = document.getElementById('btn-disable-2fa');
    const badge = document.getElementById('mfa-status-badge');
    const desc = document.getElementById('mfa-status-desc');

    if (badge) {
      badge.textContent = isEnabled ? 'ENABLED' : 'DISABLED';
      badge.style.background = isEnabled ? 'rgba(37,194,160,0.18)' : 'rgba(239,68,68,0.18)';
      badge.style.color = isEnabled ? 'var(--ok2)' : 'var(--crit)';
      badge.style.border = `1px solid ${isEnabled ? 'rgba(37,194,160,0.35)' : 'rgba(239,68,68,0.35)'}`;
    }

    if (desc) {
      desc.textContent = isEnabled
        ? 'Your account is protected by Two-Factor Authentication (TOTP). An authenticator app code is required at sign in.'
        : 'Two-factor authentication is currently disabled. Add an extra layer of defense against password theft with an authenticator app (Google Authenticator, Aegis, 1Password, Bitwarden).';
    }

    if (btnEnable) btnEnable.style.display = isEnabled ? 'none' : 'inline-flex';
    if (btnDisable) btnDisable.style.display = isEnabled ? 'inline-flex' : 'none';

  } catch (err) {
    console.warn('[USERS] Failed to fetch 2FA status:', err);
  }
}

async function start2FASetup() {
  const modal = document.getElementById('modal-setup-2fa');
  if (!modal) return;
  openModal(modal);

  const qrContainer = document.getElementById('mfa-qr-container');
  const secretKeyEl = document.getElementById('mfa-secret-key');
  const stepVerify = document.getElementById('mfa-step-verify');
  const stepSuccess = document.getElementById('mfa-step-success');

  stepVerify.style.display = 'block';
  stepSuccess.style.display = 'none';
  qrContainer.innerHTML = '<div style="color:var(--muted); padding:30px;">Generating secure TOTP key...</div>';

  try {
    const res = await apiFetch('/api/auth/mfa/setup', {
      method: 'POST',
      credentials: 'include'
    });
    if (!res.ok) throw new Error('Could not initialize TOTP setup');
    const data = await res.json();

    qrContainer.innerHTML = data.qr_svg || '';
    if (secretKeyEl) secretKeyEl.textContent = data.secret || data.totp_secret || '';

    const form = document.getElementById('form-verify-2fa');
    if (form) {
      form.reset();
      form.onsubmit = async (e) => {
        e.preventDefault();
        const code = document.getElementById('mfa-verify-code').value.trim();
        const currentPassword = document.getElementById('mfa-current-password')?.value || '';
        const verifyBtn = form.querySelector('button[type="submit"]');
        verifyBtn.disabled = true;
        verifyBtn.textContent = 'VERIFYING...';

        try {
          const verifyRes = await apiFetch('/api/auth/mfa/enable', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
              secret: data.secret || data.totp_secret,
              code,
              current_password: currentPassword,
              recovery_codes: data.recovery_codes || []
            })
          });
          const verifyData = await verifyRes.json();
          if (verifyRes.ok) {
            stepVerify.style.display = 'none';
            stepSuccess.style.display = 'block';

            const codesContainer = document.getElementById('mfa-recovery-codes-list');
            if (codesContainer && Array.isArray(verifyData.recovery_codes)) {
              codesContainer.innerHTML = verifyData.recovery_codes.map((rc) => `
                <div style="background:rgba(0,0,0,0.4); padding:6px 10px; border-radius:6px; font-family:monospace; font-size: var(--zn-fs-sm); font-weight:700; color:#38bdf8; text-align:center; border:1px solid rgba(255,255,255,0.1);">
                  ${escapeHtml(rc)}
                </div>
              `).join('');

              const copyBtn = document.getElementById('btn-copy-recovery-codes');
              if (copyBtn) {
                copyBtn.onclick = () => {
                  copyText(verifyData.recovery_codes.join('\n'));
                  copyBtn.textContent = 'COPIED TO CLIPBOARD! ✅';
                  setTimeout(() => { copyBtn.textContent = 'COPY ALL CODES'; }, 2000);
                };
              }
            }
            load2FAStatus();
            fetchCurrentProfile();
          } else {
            showToast(t('toast.verification_failed', 'Verification failed: {detail}', { detail: verifyData.detail || 'Invalid code' }), 'error');
          }
        } catch (err) {
          showToast(t('toast.error_2', 'Error: {error}', { error: err.message }), 'error');
        } finally {
          verifyBtn.disabled = false;
          verifyBtn.textContent = 'VERIFY & ACTIVATE 2FA';
        }
      };
    }

  } catch (err) {
    qrContainer.innerHTML = `<div style="color:var(--crit); padding:20px;">Error: ${escapeHtml(err.message)}</div>`;
  }
}

export function disable2FA() {
  showPromptToast(
    'Disable Two-Factor Authentication',
    'Enter your account password to confirm disabling Two-Factor Authentication:',
    '',
    async (pwd) => {
      if (!pwd) return;
      try {
        const res = await apiFetch('/api/auth/mfa/disable', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ password: pwd })
        });
        if (res.ok) {
          showToast(t('toast.two_factor_authentication_has_been_disabled', 'Two-Factor Authentication has been disabled.'), 'success');
          load2FAStatus();
          fetchCurrentProfile();
        } else {
          const err = await res.json();
          showToast(t('toast.could_not_disable_2fa', 'Could not disable 2FA: {detail}', { detail: err.detail || 'Invalid password' }), 'error');
        }
      } catch (err) {
        showToast(t('toast.request_failed', 'Request failed: {error}', { error: err.message }), 'error');
      }
    },
    null,
    { inputType: 'password', okText: 'Disable 2FA', cancelText: 'Cancel' }
  );
}
