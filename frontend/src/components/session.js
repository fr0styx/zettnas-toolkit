/**
 * The signed-in person: who it is, their name and avatar in the top bar, dock, lock screen and
 * menu. Split from users.js (PERF-9) so signing in doesn't load the Users pane's code.
 */
import { apiFetch, setSessionUserProvider } from '../api.js';
import { setServerAdvanced } from '../advanced.js';
import { t } from '../i18n.js';
import { formatRole } from './role-names.js';

let _currentUser = null;

export function setCurrentUser(user) {
  _currentUser = user;
  setServerAdvanced(user?.advanced); // UX-23: Advanced is the person's own setting
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

// Role names live in role-names.js (UX-24); re-exported for older imports
export { formatRole, ROLE_IDS } from './role-names.js';
