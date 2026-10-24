/**
 * Mission Control: Security Advisor and the HTTPS guide.
 * Split out of management.js (ARCH-1); management.js re-exports everything here.
 */
import { bringToFront } from '../dock.js';
import { api } from '../../api.js';
import { showToast } from '../../toast.js';
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';

// =========================================================================
// Security Advisor Hardening Checklist & HTTPS Guidance Modal
// =========================================================================

export function openHttpsGuideModal() {
  const overlay = document.getElementById('modal-https-guide-overlay');
  if (!overlay) return;
  const statusBanner = document.getElementById('https-guide-status-banner');
  if (statusBanner) {
    const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
    if (isHttps) {
      statusBanner.style.background = 'rgba(34,197,94,0.15)';
      statusBanner.style.border = '1px solid rgba(34,197,94,0.35)';
      statusBanner.style.color = '#22c55e';
      statusBanner.innerHTML = `<span>🔒</span> <span>${t('sec.https_status_secure', 'Active Session is Encrypted via HTTPS (TLS)')}</span>`;
    } else {
      statusBanner.style.background = 'rgba(234,179,8,0.15)';
      statusBanner.style.border = '1px solid rgba(234,179,8,0.35)';
      statusBanner.style.color = '#eab308';
      statusBanner.innerHTML = `<span>⚠️</span> <span>${t('sec.https_status_insecure', 'Active Session is Plaintext HTTP (Unencrypted)')}</span>`;
    }
  }
  overlay.style.display = 'flex';
  overlay.classList.add('open');
  const win = overlay.querySelector('.smart-modal-window');
  if (win) bringToFront(win);
}

export function closeHttpsGuideModal() {
  const overlay = document.getElementById('modal-https-guide-overlay');
  if (overlay) {
    overlay.classList.remove('open');
    overlay.style.display = 'none';
  }
}

export function handleSecurityAdvisorClick(checkId) {
  if (!checkId) return;

  switch (checkId) {
    case 'default_password':
    case 'sec_default_password': {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-system-group', 'mgmt-pane-security');
      }
      setTimeout(() => {
        const newPwdInput = document.getElementById('sec-new-pwd');
        const confirmPwdInput = document.getElementById('sec-confirm-pwd');
        if (newPwdInput) {
          try {
            newPwdInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } catch (_) {
            newPwdInput.scrollIntoView();
          }
          newPwdInput.focus();
          newPwdInput.classList.remove('element-focus-pulse');
          void newPwdInput.offsetWidth;
          newPwdInput.classList.add('element-focus-pulse');
          setTimeout(() => newPwdInput.classList.remove('element-focus-pulse'), 1500);
        }
        if (confirmPwdInput) {
          confirmPwdInput.classList.remove('element-focus-pulse');
          void confirmPwdInput.offsetWidth;
          confirmPwdInput.classList.add('element-focus-pulse');
          setTimeout(() => confirmPwdInput.classList.remove('element-focus-pulse'), 1500);
        }
        showToast(t('sec.toast_password_focus', 'Configure your new administrator password below.'), 'info');
      }, 100);
      break;
    }

    case 'admin_mfa':
    case 'sec_superadmin_mfa':
    case 'mfa_admins': {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-system-group', 'mgmt-pane-users', 'users-pane-2fa');
      }
      setTimeout(() => {
        const mfaCard = document.getElementById('mfa-status-card') || document.getElementById('users-pane-2fa');
        if (mfaCard) {
          try {
            mfaCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } catch (_) {
            mfaCard.scrollIntoView();
          }
          mfaCard.classList.remove('element-focus-pulse');
          void mfaCard.offsetWidth;
          mfaCard.classList.add('element-focus-pulse');
          setTimeout(() => mfaCard.classList.remove('element-focus-pulse'), 1500);
        }
      }, 150);
      break;
    }

    case 'https_transport': {
      openHttpsGuideModal();
      break;
    }

    case 'smb_guest_access': {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-storage', 'mgmt-pane-storage-shares');
      }
      setTimeout(() => {
        const sharesMount = document.getElementById('mgmt-storage-shares-mount') || document.getElementById('mgmt-pane-storage-shares');
        if (sharesMount) {
          try {
            sharesMount.scrollIntoView({ behavior: 'smooth', block: 'start' });
          } catch (_) {
            sharesMount.scrollIntoView();
          }
          sharesMount.classList.remove('element-focus-pulse');
          void sharesMount.offsetWidth;
          sharesMount.classList.add('element-focus-pulse');
          setTimeout(() => sharesMount.classList.remove('element-focus-pulse'), 1500);
        }
        showToast(t('sec.toast_shares_focus', 'Inspect and manage network share permissions and guest access settings.'), 'info');
      }, 150);
      break;
    }

    case 'stale_api_tokens': {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-system-group', 'mgmt-pane-security');
      }
      setTimeout(() => {
        const tokensList = document.getElementById('api-tokens-list');
        const tokenNameInput = document.getElementById('new-token-name');
        if (tokenNameInput) {
          try {
            tokenNameInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } catch (_) {
            tokenNameInput.scrollIntoView();
          }
          tokenNameInput.focus();
          tokenNameInput.classList.remove('element-focus-pulse');
          void tokenNameInput.offsetWidth;
          tokenNameInput.classList.add('element-focus-pulse');
          setTimeout(() => tokenNameInput.classList.remove('element-focus-pulse'), 1500);
        }
        if (tokensList) {
          tokensList.classList.remove('element-focus-pulse');
          void tokensList.offsetWidth;
          tokensList.classList.add('element-focus-pulse');
          setTimeout(() => tokensList.classList.remove('element-focus-pulse'), 1500);
        }
        showToast(t('sec.toast_tokens_focus', 'Manage and rotate active API integration tokens below.'), 'info');
      }, 100);
      break;
    }

    case 'sec_default_admin': {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-system-group', 'mgmt-pane-security');
      }
      setTimeout(() => {
        const disableContainer = document.getElementById('sec-disable-admin-container');
        const disableBtn = document.getElementById('btn-disable-default-admin');
        if (disableContainer) {
          try {
            disableContainer.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } catch (_) {
            disableContainer.scrollIntoView();
          }
          disableContainer.classList.remove('element-focus-pulse');
          void disableContainer.offsetWidth;
          disableContainer.classList.add('element-focus-pulse');
          setTimeout(() => disableContainer.classList.remove('element-focus-pulse'), 1500);
        }
        if (disableBtn && !disableBtn.disabled) {
          disableBtn.focus();
        }
      }, 100);
      break;
    }

    case 'sec_superadmin_redundancy': {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow('mgmt-sec-system-group', 'mgmt-pane-users', 'users-pane-list');
      }
      setTimeout(() => {
        const btnAdd = document.getElementById('btn-add-user');
        if (btnAdd) {
          btnAdd.focus();
          btnAdd.classList.add('element-focus-pulse');
          setTimeout(() => btnAdd.classList.remove('element-focus-pulse'), 1500);
        }
      }, 150);
      break;
    }

    default:
      console.info('[SecurityAdvisor] Clicked check:', checkId);
      break;
  }
}

export async function fetchAndRenderSecurityPosture() {
  const badge = document.getElementById('sec-advisor-score-badge');
  const container = document.getElementById('sec-advisor-items');
  if (!badge && !container) return;

  try {
    const data = await api.get('/api/system/security-posture');
    if (!data) return;

    if (badge) {
      badge.textContent = `Score: ${data.score}/100 (Grade ${data.grade})`;
      if (data.score >= 90) {
        badge.style.background = 'rgba(37,194,160,0.15)';
        badge.style.color = '#25c2a0';
        badge.style.borderColor = 'rgba(37,194,160,0.3)';
      } else if (data.score >= 75) {
        badge.style.background = 'rgba(56,189,248,0.15)';
        badge.style.color = '#38bdf8';
        badge.style.borderColor = 'rgba(56,189,248,0.3)';
      } else if (data.score >= 50) {
        badge.style.background = 'rgba(234,179,8,0.15)';
        badge.style.color = '#eab308';
        badge.style.borderColor = 'rgba(234,179,8,0.3)';
      } else {
        badge.style.background = 'rgba(239,68,68,0.15)';
        badge.style.color = '#ef4444';
        badge.style.borderColor = 'rgba(239,68,68,0.3)';
      }
    }

    if (container && Array.isArray(data.checks)) {
      container.innerHTML = data.checks.map(c => {
        const passIcon = c.passed ? '✔' : '✖';
        const passColor = c.passed ? '#22c55e' : '#ef4444';
        const badgeBg = c.passed ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)';
        const actionText = c.passed ? t('sec.action_review', 'Review ➔') : t('sec.action_configure', 'Configure ➔');
        return `
          <div class="sec-advisor-item ${c.passed ? 'passed' : 'needs-action'}" data-check-id="${escapeHtml(c.id)}" role="button" tabindex="0" title="${t('sec.click_to_configure', 'Click to configure')}" style="background:${badgeBg}; border:1px solid ${c.passed ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.3)'};">
            <div style="display:flex; align-items:center; gap:10px; flex:1; min-width:0;">
              <span class="sec-advisor-item-icon" style="color:${passColor}; font-weight:800; font-size: var(--zn-fs-sm); line-height:1;">${passIcon}</span>
              <div style="min-width:0;">
                <div style="font-weight:600; color:#f8fafc; font-size: var(--zn-fs-sm); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(c.name)}</div>
                <div style="font-size: var(--zn-fs-xs); color:${c.passed ? '#94a3b8' : '#fca5a5'}; margin-top:2px;">${escapeHtml(c.details || '')}</div>
              </div>
            </div>
            <div style="display:flex; align-items:center; gap:8px; flex-shrink:0;">
              <span class="sec-advisor-status-badge" style="font-size: var(--zn-fs-xs); font-weight:700; color:${passColor}; text-transform:uppercase; letter-spacing:0.5px;">${c.passed ? 'PASSED' : 'NEEDS ACTION'}</span>
              <span class="sec-advisor-action-pill">${actionText}</span>
            </div>
          </div>
        `;
      }).join('');

      container.querySelectorAll('.sec-advisor-item').forEach(item => {
        const checkId = item.dataset.checkId;
        const trigger = () => handleSecurityAdvisorClick(checkId);
        item.addEventListener('click', trigger);
        item.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            trigger();
          }
        });
      });
    }
  } catch (err) {
    console.warn('[SecurityPosture] Failed to fetch posture:', err);
  }
}

if (typeof window !== 'undefined') {
  window.handleSecurityAdvisorClick = handleSecurityAdvisorClick;
  window.fetchAndRenderSecurityPosture = fetchAndRenderSecurityPosture;
  window.openHttpsGuideModal = openHttpsGuideModal;
  window.closeHttpsGuideModal = closeHttpsGuideModal;
}
