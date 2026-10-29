/**
 * ZettNAS Toolkit - Multi-User Identity, RBAC & Two-Factor Authentication Component
 * Handles User inventory, Role assignment, Session revocation, and TOTP 2FA setup.
 */

import { onManagementDom } from '../management-dom.js';
import { api, auth, apiFetch } from '../api.js';
import {
  setCurrentUser,
  getCurrentUser,
  fetchCurrentProfile,
  updateUserInterfaceElements,
  formatRole,
} from './session.js';
import { escapeHtml, trapFocus, copyText } from '../utils.js';
import { ZettEventBus } from '../event-bus.js';
import { t } from '../i18n.js';
import { showToast, showConfirmToast, showPromptToast } from '../toast.js';
import { initTopbarUserPill } from './dock.js';
import { grantShares, openShareAccessModal, shareChoicesHtml } from './share-access.js';

import { formatDateTime } from '../format.js';
import { setServerAdvanced } from '../advanced.js';
import { renderInvites } from './invites.js';
import { emptyRowHtml } from './empty-state.js';
// The signed-in person's state lives in session.js (PERF-9); re-exported for older imports
export { setCurrentUser, getCurrentUser, fetchCurrentProfile, updateUserInterfaceElements, formatRole };

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
  container.innerHTML = '<tr><td colspan="7" style="text-align:center; padding: 24px; color: var(--muted);">' + escapeHtml(t('users.loading', 'Loading people…')) + '</td></tr>';

  try {
    const res = await apiFetch('/api/users', { credentials: 'include' });
    if (!res.ok) {
      if (res.status === 403) {
        container.innerHTML = '<tr><td colspan="7" style="text-align:center; padding: 24px; color: var(--crit);">' + escapeHtml(t('users.admin_only', 'Only administrators can see the list of people.')) + '</td></tr>';
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
      const isSelf = getCurrentUser()?.id === u.id;
      const quotaStr = u.storage_quota_bytes > 0
        ? `${Math.round(u.storage_quota_bytes / (1024 * 1024 * 1024))} GB`
        : t('users.no_limit', 'No limit');

      return `
        <tr style="border-bottom: 1px solid var(--zn-line-6); transition: background 0.15s ease;">
          <td style="padding: 12px; display:flex; align-items:center; gap: 10px;">
            <div style="width: 32px; height: 32px; border-radius: 50%; background: linear-gradient(135deg, #0284c7, #0369a1); display:flex; align-items:center; justify-content:center; font-weight:800; color:#fff; font-size: var(--zn-fs-sm); border: 1px solid var(--zn-line-20);">
              ${escapeHtml(letter)}
            </div>
            <div>
              <div style="font-weight:700; color:var(--zn-text-strong); font-size: var(--zn-fs-sm);">${escapeHtml(u.display_name || u.username)} ${isSelf ? '<span style="font-size: var(--zn-fs-xs); background:rgba(14,165,233,0.2); color:var(--zn-text-accent); padding:2px 6px; border-radius:4px; margin-left:4px;">' + escapeHtml(t('users.you', 'You')) + '</span>' : ''}</div>
              <div style="font-size: var(--zn-fs-xs); color:var(--muted);">@${escapeHtml(u.username)}</div>
            </div>
          </td>
          <td style="padding: 12px; font-size: var(--zn-fs-sm); color:var(--zn-text-soft);">${escapeHtml(u.email || '--')}</td>
          <td style="padding: 12px;">
            <span style="font-size: var(--zn-fs-xs); font-weight: 700; padding: 3px 8px; border-radius: 6px; background: var(--zn-glaze-8); border: 1px solid var(--zn-line-12); color:var(--zn-text-strong);">
              ${escapeHtml(formatRole(u.role_id))}
            </span>
          </td>
          <td style="padding: 12px;">
            <span style="font-size: var(--zn-fs-xs); font-weight: 700; padding: 2px 7px; border-radius: 4px; background: ${isActive ? 'rgba(37,194,160,0.15)' : 'rgba(239,68,68,0.15)'}; color: ${isActive ? 'var(--ok2)' : 'var(--crit)'}; border: 1px solid ${isActive ? 'rgba(37,194,160,0.3)' : 'rgba(239,68,68,0.3)'};">
              ${escapeHtml(isActive ? t('users.status_active', 'Active') : t('users.status_disabled', 'Turned off'))}
            </span>
          </td>
          <td style="padding: 12px;">
            <span style="font-size: var(--zn-fs-xs); display:inline-flex; align-items:center; gap: 4px; color: ${isMfa ? 'var(--ok2)' : 'var(--muted)'};">
              <span aria-hidden="true">${isMfa ? '🛡️' : '⚪'}</span> ${escapeHtml(isMfa ? t('users.mfa_on', 'On') : t('users.mfa_off', 'Off'))}
            </span>
          </td>
          <td style="padding: 12px; font-size: var(--zn-fs-sm); color: var(--zn-text-muted);">${quotaStr}</td>
          <td style="padding: 12px; text-align:right;">
            <div style="display:inline-flex; gap: 6px;">
              <button class="suite-toolkit-btn sm btn-edit-user" data-id="${u.id}" title="${t('ui.edit_user', 'Edit User')}">✏️</button>
              <button class="suite-toolkit-btn sm btn-pwd-user" data-id="${u.id}" data-user="${escapeHtml(u.username)}" title="${t('ui.reset_password', 'Reset Password')}">🔑</button>
              ${!isSelf ? `
                <button class="suite-toolkit-btn sm btn-toggle-user" data-id="${u.id}" data-status="${u.status}" title="${escapeHtml(isActive ? t('users.turn_off', 'Turn off this account') : t('users.turn_on', 'Turn on this account'))}">
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
    container.innerHTML = '<tr><td colspan="7" style="text-align:center; padding: 24px; color: var(--crit);">' + escapeHtml(t('users.load_failed', 'The list of people couldn\'t be loaded: {error}', { error: err.message })) + '</td></tr>';
  }
}

/** New people reach no shared folder until given one (B11, SEC-21), so the dialog asks which. */
export async function loadAddUserShares() {
  const wrap = document.getElementById('add-user-shares-wrap');
  const list = document.getElementById('add-user-shares');
  if (!wrap || !list) return;
  wrap.hidden = true;
  list.innerHTML = '';
  try {
    const data = await api.get('/api/storage/share-access');
    if (!data?.shares?.length) return;
    list.innerHTML = shareChoicesHtml(data.shares);
    wrap.hidden = false;
  } catch {
    // no right to manage share access: the dialog works without the list
  }
}

export async function grantChosenShares(username) {
  const levels = {};
  document.querySelectorAll('#add-user-shares select[data-add-user-share]').forEach((sel) => {
    levels[sel.dataset.addUserShare] = sel.value;
  });
  try {
    await grantShares(username, levels);
  } catch (err) {
    showToast(t('users.shares_failed', '{name} was added, but their shared folders were not set: {error}', { name: username, error: err.message }), 'warning');
  }
}

export function showAddUserModal() {
  const modal = document.getElementById('modal-add-user');
  if (!modal) return;
  openModal(modal);
  loadAddUserShares();
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
      submitBtn.textContent = t('users.creating', 'Adding…');

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
          await grantChosenShares(username);
          loadUsersList();
          showToast(t('toast.user_created_successfully', 'User created successfully.'), 'success');
        } else {
          showToast(t('toast.error', 'Error: {detail}', { detail: result.detail || result.error || 'Failed to create user' }), 'error');
        }
      } catch (err) {
        showToast(t('toast.request_failed', 'Request failed: {error}', { error: err.message }), 'error');
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = t('users.create', 'Add person');
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

  import('./management/user-data.js').then((m) => m.installUserDataFor(modal, user)).catch(() => {}); // B8
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
      submitBtn.textContent = t('setup.saving', 'Saving...');

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
        submitBtn.textContent = t('users.save_changes', 'Save changes');
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
  const isSelf = !!getCurrentUser() && getCurrentUser().id === userId;
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
      submitBtn.textContent = t('users.updating', 'Changing…');

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
          showToast(isSelf ? t('users.pwd_changed_self', 'Password changed. Your other sessions were signed out.') : t('users.pwd_changed_other', 'Password changed. They were signed out everywhere.'), 'success');
          closeModal(modal);
        } else {
          const err = await res.json();
          showToast(t('toast.error', 'Error: {detail}', { detail: err.detail || 'Failed to reset password' }), 'error');
        }
      } catch (err) {
        showToast(t('toast.request_failed', 'Request failed: {error}', { error: err.message }), 'error');
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = t('users.update_password', 'Change password');
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
    t('users.delete_title', 'Delete this person?'),
    t('users.delete_msg', '@{username} loses their account and is signed out everywhere. Their files stay where they are.', { username }),
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
    { okText: t('users.delete_user', 'Delete User'), destructive: true, typeToConfirm: username }
  );
}

export async function loadSessionsList() {
  const container = document.getElementById('sessions-table-body');
  if (!container) return;
  container.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 24px; color: var(--muted);">' + escapeHtml(t('users.sessions_loading', 'Loading sign-ins…')) + '</td></tr>';

  try {
    const res = await apiFetch('/api/auth/sessions', { credentials: 'include' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const sessions = data.sessions || [];

    if (sessions.length === 0) {
      container.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 24px; color: var(--muted);">' + escapeHtml(t('users.sessions_none', 'No other sign-ins.')) + '</td></tr>';
      return;
    }

    container.innerHTML = sessions.map((s) => {
      const createdStr = formatDateTime(s.created_at);
      const lastStr = formatDateTime(s.last_active_at);
      const isCurrent = !!s.is_current;

      return `
        <tr style="border-bottom: 1px solid var(--zn-line-6);">
          <td style="padding: 12px; font-weight:700; color:var(--zn-text-strong);">
            <span aria-hidden="true">${isCurrent ? '💻' : '🌐'}</span> ${escapeHtml(isCurrent ? t('users.this_browser', 'This browser') : t('users.other_device', 'Another device'))}
            ${isCurrent ? '<span style="font-size: var(--zn-fs-xs); background:rgba(37,194,160,0.2); color:var(--ok2); padding:2px 6px; border-radius:4px; margin-left:6px;">' + escapeHtml(t('users.this_device', 'This device')) + '</span>' : ''}
            <div style="font-size: var(--zn-fs-xs); font-weight:normal; color:var(--muted); margin-top:2px;">${escapeHtml(s.user_agent || t('users.unknown_browser', 'Unknown browser'))}</div>
          </td>
          <td style="padding: 12px; font-size: var(--zn-fs-sm); color:var(--zn-text-soft); font-family:monospace;">${escapeHtml(s.ip_address || '127.0.0.1')}</td>
          <td style="padding: 12px; font-size: var(--zn-fs-sm); color:var(--zn-text-muted);">${createdStr}</td>
          <td style="padding: 12px; font-size: var(--zn-fs-sm); color:var(--zn-text-muted);">${lastStr}</td>
          <td style="padding: 12px; text-align:right;">
            ${!isCurrent ? `
              <button class="suite-toolkit-btn sm danger btn-revoke-session" data-id="${s.id}">${escapeHtml(t('users.sign_out', 'Sign out'))}</button>
            ` : '<span style="font-size: var(--zn-fs-xs); color:var(--muted);">' + escapeHtml(t('users.in_use', 'In use')) + '</span>'}
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
    container.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 24px; color: var(--crit);">' + escapeHtml(t('users.sessions_failed', 'The sign-ins couldn\'t be loaded: {error}', { error: err.message })) + '</td></tr>';
  }
}

export function revokeAllOtherSessions() {
  showConfirmToast(
    t('users.sign_out_others', 'Sign out everywhere else'),
    t('users.sign_out_others_msg', 'Sign out every other browser and device? You stay signed in here.'),
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
    { okText: t('users.sign_out_others', 'Sign out everywhere else'), cancelText: t('common.cancel', 'Cancel') }
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
      badge.textContent = isEnabled ? t('users.2fa_badge_on', 'On') : t('users.2fa_badge_off', 'Off');
      badge.style.background = isEnabled ? 'rgba(37,194,160,0.18)' : 'rgba(239,68,68,0.18)';
      badge.style.color = isEnabled ? 'var(--ok2)' : 'var(--crit)';
      badge.style.border = `1px solid ${isEnabled ? 'rgba(37,194,160,0.35)' : 'rgba(239,68,68,0.35)'}`;
    }

    if (desc) {
      desc.textContent = isEnabled
        ? t('users.2fa_desc_on', 'Two-step sign-in is on: signing in asks for a code from your authenticator app.')
        : t('users.2fa_desc_off', 'Two-step sign-in is off. Turn it on, and a stolen password alone can\'t open your account.');
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
  qrContainer.innerHTML = '<div style="color:var(--muted); padding:30px;">' + escapeHtml(t('users.2fa_preparing', 'Preparing the key…')) + '</div>';

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
        verifyBtn.textContent = t('signin.verifying', 'Checking…');

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
                <div style="background:var(--zn-shade-40); padding:6px 10px; border-radius:6px; font-family:monospace; font-size: var(--zn-fs-sm); font-weight:700; color:var(--zn-text-accent); text-align:center; border:1px solid var(--zn-line-10);">
                  ${escapeHtml(rc)}
                </div>
              `).join('');

              const copyBtn = document.getElementById('btn-copy-recovery-codes');
              if (copyBtn) {
                copyBtn.onclick = () => {
                  copyText(verifyData.recovery_codes.join('\n'));
                  copyBtn.textContent = t('users.2fa_copied', 'Copied');
                  setTimeout(() => { copyBtn.textContent = t('users.2fa_copy_codes', 'Copy all codes'); }, 2000);
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
          verifyBtn.textContent = t('users.2fa_activate', 'Check the code and turn on');
        }
      };
    }

  } catch (err) {
    qrContainer.innerHTML = '<div style="color:var(--crit); padding:20px;">' + escapeHtml(t('users.2fa_error', 'Two-step sign-in couldn\'t be set up: {error}', { error: err.message })) + '</div>';
  }
}

export function disable2FA() {
  showPromptToast(
    'Disable Two-Factor Authentication',
    'Enter your account password to confirm disabling Two-Factor Authentication:',
    '',
    (pwd) => {
      if (!pwd) return;
      // SEC-27: the password and a current code (or a recovery code) are both needed
      showPromptToast(
        t('mfa.disable_title', 'Turn off two-factor sign-in'),
        t('mfa.disable_code_prompt', 'Enter the 6-digit code from your authenticator app, or one of your recovery codes:'),
        '',
        (code) => (code ? _sendDisable2FA(pwd, code.trim()) : undefined),
        null,
        { okText: t('mfa.disable_ok', 'Turn off'), cancelText: t('common.cancel', 'Cancel') }
      );
    },
    null,
    { inputType: 'password', okText: t('common.next', 'Next'), cancelText: t('common.cancel', 'Cancel') }
  );
}

async function _sendDisable2FA(pwd, code) {
  try {
    const res = await apiFetch('/api/auth/mfa/disable', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ password: pwd, code })
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
}
