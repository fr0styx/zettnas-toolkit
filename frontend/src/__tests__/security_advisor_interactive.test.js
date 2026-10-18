import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  fetchAndRenderSecurityPosture,
  handleSecurityAdvisorClick,
  openHttpsGuideModal,
  closeHttpsGuideModal,
} from '../components/management.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

describe('Security Advisor Hardening Checklist - Interactive Configuration Routing', () => {
  let container;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    window.openManagementWindow = vi.fn();

    container = document.createElement('div');
    container.innerHTML = `
      <div id="sec-advisor-score-badge"></div>
      <div id="sec-advisor-items"></div>
      <div id="sec-disable-admin-container" style="display:none;">
        <button id="btn-disable-default-admin"></button>
      </div>

      <div id="mgmt-pane-security">
        <input type="password" id="sec-new-pwd" value="" />
        <input type="password" id="sec-confirm-pwd" value="" />
        <div id="api-tokens-list"></div>
        <input type="text" id="new-token-name" value="" />
        <button type="button" id="btn-jump-to-2fa">Configure 2FA</button>
      </div>

      <div id="mgmt-pane-users">
        <div id="mfa-status-card"></div>
        <div id="users-pane-2fa"></div>
        <button id="btn-add-user"></button>
      </div>

      <div id="mgmt-pane-storage-shares">
        <div id="mgmt-storage-shares-mount"></div>
      </div>

      <!-- HTTPS Modal -->
      <div id="modal-https-guide-overlay" class="smart-modal-backdrop" style="display:none;">
        <div class="smart-modal-window">
          <button id="modal-https-guide-close"></button>
          <div id="https-guide-status-banner"></div>
          <button id="btn-https-guide-apps">Apps</button>
          <button id="btn-https-guide-ports">Ports</button>
          <button id="btn-copy-tailscale-serve">Copy</button>
          <button id="btn-modal-https-guide-close">Close</button>
        </div>
      </div>
    `;
    document.body.appendChild(container);

    // Mock scrollIntoView and focus
    Element.prototype.scrollIntoView = vi.fn();
    HTMLElement.prototype.focus = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
    container?.remove();
    vi.restoreAllMocks();
    delete window.openManagementWindow;
  });

  it('renders interactive items with action pills and data-check-id', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      score: 85,
      grade: 'B',
      checks: [
        { id: 'default_password', name: 'Default Administrator Password', passed: false, details: 'Default password detected' },
        { id: 'admin_mfa', name: 'Administrator Two-Factor Authentication (2FA)', passed: false, details: 'Lacks 2FA' },
        { id: 'https_transport', name: 'HTTPS Transport Encryption', passed: true, details: 'TLS active' },
        { id: 'smb_guest_access', name: 'SMB Network Share Guest Access', passed: true, details: 'No guest access' },
        { id: 'stale_api_tokens', name: 'API Token Hygiene', passed: true, details: 'Tokens active' }
      ]
    });

    await fetchAndRenderSecurityPosture();

    const items = container.querySelectorAll('.sec-advisor-item');
    expect(items.length).toBe(5);

    const first = items[0];
    expect(first.dataset.checkId).toBe('default_password');
    expect(first.getAttribute('role')).toBe('button');
    expect(first.getAttribute('tabindex')).toBe('0');
    expect(first.querySelector('.sec-advisor-action-pill')?.textContent).toContain('Configure');

    const third = items[2];
    expect(third.dataset.checkId).toBe('https_transport');
    expect(third.querySelector('.sec-advisor-action-pill')?.textContent).toContain('Review');
  });

  it('clicking Default Administrator Password scrolls and focuses password fields with pulse effect', () => {
    const newPwd = document.getElementById('sec-new-pwd');
    const scrollSpy = vi.spyOn(newPwd, 'scrollIntoView');
    const focusSpy = vi.spyOn(newPwd, 'focus');

    handleSecurityAdvisorClick('default_password');

    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-system-group', 'mgmt-pane-security');

    vi.advanceTimersByTime(120);

    expect(scrollSpy).toHaveBeenCalled();
    expect(focusSpy).toHaveBeenCalled();
    expect(newPwd.classList.contains('element-focus-pulse')).toBe(true);

    vi.advanceTimersByTime(1600);
    expect(newPwd.classList.contains('element-focus-pulse')).toBe(false);
  });

  it('clicking Administrator 2FA navigates to Users & Roles 2FA subpane', () => {
    const mfaCard = document.getElementById('mfa-status-card');
    const scrollSpy = vi.spyOn(mfaCard, 'scrollIntoView');

    handleSecurityAdvisorClick('admin_mfa');

    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-system-group', 'mgmt-pane-users', 'users-pane-2fa');

    vi.advanceTimersByTime(160);
    expect(scrollSpy).toHaveBeenCalled();
    expect(mfaCard.classList.contains('element-focus-pulse')).toBe(true);
  });

  it('clicking HTTPS Transport Encryption opens interactive guidance modal and routes actions', () => {
    const overlay = document.getElementById('modal-https-guide-overlay');
    expect(overlay.style.display).toBe('none');

    handleSecurityAdvisorClick('https_transport');

    expect(overlay.style.display).toBe('flex');
    expect(overlay.classList.contains('open')).toBe(true);

    const banner = document.getElementById('https-guide-status-banner');
    expect(banner.textContent).toBeTruthy();

    closeHttpsGuideModal();
    expect(overlay.style.display).toBe('none');
    expect(overlay.classList.contains('open')).toBe(false);
  });

  it('clicking SMB Network Share Guest Access navigates to storage shares pane', () => {
    const sharesMount = document.getElementById('mgmt-storage-shares-mount');
    const scrollSpy = vi.spyOn(sharesMount, 'scrollIntoView');

    handleSecurityAdvisorClick('smb_guest_access');

    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-storage', 'mgmt-pane-storage-shares');

    vi.advanceTimersByTime(160);
    expect(scrollSpy).toHaveBeenCalled();
    expect(sharesMount.classList.contains('element-focus-pulse')).toBe(true);
  });

  it('clicking API Token Hygiene scrolls to and focuses new token input', () => {
    const tokenInput = document.getElementById('new-token-name');
    const scrollSpy = vi.spyOn(tokenInput, 'scrollIntoView');
    const focusSpy = vi.spyOn(tokenInput, 'focus');

    handleSecurityAdvisorClick('stale_api_tokens');

    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-system-group', 'mgmt-pane-security');

    vi.advanceTimersByTime(120);
    expect(scrollSpy).toHaveBeenCalled();
    expect(focusSpy).toHaveBeenCalled();
  });
});
