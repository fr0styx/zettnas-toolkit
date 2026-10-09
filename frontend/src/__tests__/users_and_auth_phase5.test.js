import { describe, it, expect, beforeEach, vi } from 'vitest';
import { formatRole, setCurrentUser, getCurrentUser, updateUserInterfaceElements } from '../components/users.js';

describe('Phase 5: Multi-User Identity, RBAC & Desktop Lock UI', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="os-dock"></div>
      <div id="topbar-user-avatar-initial"></div>
      <div id="topbar-user-display-name"></div>
      <div id="dock-user-avatar-initial"></div>
      <div id="dock-user-display-name"></div>
      <div id="lock-avatar"></div>
      <div id="lock-display-name"></div>
      <div id="lock-role-badge"></div>
      <div id="user-flyout-avatar"></div>
      <div id="user-flyout-name"></div>
      <div id="user-flyout-username"></div>
      <div id="user-flyout-role"></div>
      <button id="mgmt-tab-users"></button>

      <!-- Users pane -->
      <div id="mgmt-pane-users">
        <button class="users-nav-btn active" data-tab="users-pane-list">Users</button>
        <button class="users-nav-btn" data-tab="users-pane-sessions">Sessions</button>
        <button class="users-nav-btn" data-tab="users-pane-2fa">2FA</button>

        <div id="users-pane-list" class="users-subpane" style="display: block;"></div>
        <div id="users-pane-sessions" class="users-subpane" style="display: none;"></div>
        <div id="users-pane-2fa" class="users-subpane" style="display: none;"></div>
      </div>
    `;
  });

  it('formats role IDs into human-readable labels with security badges', () => {
    expect(formatRole('superadmin')).toContain('SuperAdmin');
    expect(formatRole('storage_admin')).toContain('Storage Admin');
    expect(formatRole('app_operator')).toContain('App Operator');
    expect(formatRole('backup_operator')).toContain('Backup Operator');
    expect(formatRole('share_user')).toContain('Family & Share User');
    expect(formatRole('auditor')).toContain('Auditor & Viewer');
  });

  it('updates interface elements across dock, lock screen, and flyout when current user is set', () => {
    const user = {
      id: 'usr_test123',
      username: 'johndoe',
      display_name: 'John Doe',
      role_id: 'superadmin',
      scopes: ['*']
    };

    setCurrentUser(user);
    expect(getCurrentUser()).toEqual(user);

    expect(document.getElementById('topbar-user-avatar-initial').textContent).toBe('J');
    expect(document.getElementById('topbar-user-display-name').textContent).toBe('John Doe');
    expect(document.getElementById('dock-user-avatar-initial').textContent).toBe('J');
    expect(document.getElementById('dock-user-display-name').textContent).toBe('John Doe');
    expect(document.getElementById('lock-display-name').textContent).toBe('John Doe');
    expect(document.getElementById('lock-role-badge').textContent).toContain('SuperAdmin');
    expect(document.getElementById('user-flyout-name').textContent).toBe('John Doe');
    expect(document.getElementById('user-flyout-username').textContent).toBe('@johndoe');

    // Admin has access to users tab
    expect(document.getElementById('mgmt-tab-users').style.display).not.toBe('none');
  });

  it('dynamically hides Users management tab for standard share_user without users:read scope', () => {
    const regularUser = {
      id: 'usr_family1',
      username: 'alice',
      display_name: 'Alice',
      role_id: 'share_user',
      scopes: ['storage:read', 'shares:read']
    };

    setCurrentUser(regularUser);
    expect(document.getElementById('mgmt-tab-users').style.display).toBe('none');
  });

  it('openModal adds open class and sets display flex, closeModal removes open and sets none', async () => {
    const { openModal, closeModal } = await import('../components/users.js');
    const modal = document.createElement('div');
    modal.className = 'smart-modal-backdrop';
    document.body.appendChild(modal);

    openModal(modal);
    expect(modal.classList.contains('open')).toBe(true);
    expect(modal.style.display).toBe('flex');

    closeModal(modal);
    expect(modal.classList.contains('open')).toBe(false);
    expect(modal.style.display).toBe('none');
  });

  it('lockDesktop persists lock state in sessionStorage and marks documentElement is-desktop-locked', async () => {
    const { lockDesktop, isDesktopLocked } = await import('../components/auth.js');
    const lockOverlay = document.createElement('div');
    lockOverlay.id = 'lock-overlay';
    document.body.appendChild(lockOverlay);

    lockDesktop();
    expect(isDesktopLocked()).toBe(true);
    expect(sessionStorage.getItem('zettnas_desktop_locked')).toBe('true');
    expect(document.documentElement.classList.contains('is-desktop-locked')).toBe(true);
    expect(document.body.classList.contains('desktop-locked')).toBe(true);
    expect(lockOverlay.style.display).toBe('flex');
  });

  it('switchUser clears desktop lock and enters chooser mode', async () => {
    const { switchUser, isDesktopLocked } = await import('../components/auth.js');
    const lockOverlay = document.createElement('div');
    lockOverlay.id = 'lock-overlay';
    const loginOverlay = document.createElement('div');
    loginOverlay.id = 'login-overlay';
    const chooser = document.createElement('div');
    chooser.id = 'login-users-chooser';
    const manualFields = document.createElement('div');
    manualFields.id = 'login-manual-fields';
    const selectedCard = document.createElement('div');
    selectedCard.id = 'login-user-selected-card';

    document.body.appendChild(lockOverlay);
    document.body.appendChild(loginOverlay);
    document.body.appendChild(chooser);
    document.body.appendChild(manualFields);
    document.body.appendChild(selectedCard);

    sessionStorage.setItem('zettnas_desktop_locked', 'true');
    document.documentElement.classList.add('is-desktop-locked');

    switchUser();
    expect(isDesktopLocked()).toBe(false);
    expect(sessionStorage.getItem('zettnas_desktop_locked')).toBe(null);
    expect(document.documentElement.classList.contains('is-desktop-locked')).toBe(false);
    expect(document.documentElement.classList.contains('auth-required')).toBe(true);
  });

  it('logout clears session, user state, and removes lock state', async () => {
    const { logout } = await import('../components/auth.js');
    sessionStorage.setItem('zettnas_desktop_locked', 'true');
    document.documentElement.classList.add('is-desktop-locked');

    await logout();
    expect(sessionStorage.getItem('zettnas_desktop_locked')).toBe(null);
    expect(document.documentElement.classList.contains('is-desktop-locked')).toBe(false);
    expect(getCurrentUser()).toBe(null);
    expect(document.documentElement.classList.contains('auth-required')).toBe(true);
  });
});
