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
      statusBanner.innerHTML = `<span aria-hidden="true">🔒</span> <span>${t('sec.https_status_secure', 'Active Session is Encrypted via HTTPS (TLS)')}</span>`;
    } else {
      statusBanner.style.background = 'rgba(234,179,8,0.15)';
      statusBanner.style.border = '1px solid rgba(234,179,8,0.35)';
      statusBanner.style.color = '#eab308';
      statusBanner.innerHTML = `<span aria-hidden="true">⚠️</span> <span>${t('sec.https_status_insecure', 'Active Session is Plaintext HTTP (Unencrypted)')}</span>`;
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

    default: {
      // ten kinds of row did nothing here (SET-14): a row with a one-click fix offers it (the
      // server asks first), the others open the place where they are dealt with
      if (FIXABLE.includes(checkId)) {
        applySecurityFix(checkId);
      } else {
        const [section, pane] = PLACES[checkId] || ['mgmt-sec-system-group', 'mgmt-pane-security'];
        /** @type {any} */ (window).openManagementWindow?.(section, pane);
      }
      break;
    }
  }
}

/** A row's state: passed, a suggestion (costs no points, e.g. a second administrator), or a finding. */
export function checkState(c) {
  if (c.passed) return 'ok';
  return Number(c.penalty) === 0 ? 'tip' : 'look';
}
/** A row's name in the reader's language (the server's English when there is no text for it). */
export function checkName(c) {
  return t(`sec.check.${c.id}`, c.name || '');
}

/** A row's sentence: translated when the server said what goes into it (`params`), else its own. */
export function checkDetails(c) {
  if (!c.params || typeof c.params !== 'object') return c.details || '';
  return t(`sec.check.${c.id}.${c.passed ? 'ok' : 'look'}`, c.details || '', c.params);
}

const STATE_WORD = {
  ok: () => t('sec.state_ok', 'Passed'),
  tip: () => t('sec.state_tip', 'Suggestion'),
  look: () => t('sec.state_look', 'Needs action'),
};

// the safe-defaults findings that carry a fix of the same name (backend/services/safe_defaults_advisor.py)
export const FIXABLE = ['share_access_family', 'nfs_open_exports', 'auditor_reads_everything', 'ai_search_family', 'snapshots_off'];
const PLACES = {
  ai_runtime_exposure: ['mgmt-sec-ai', 'mgmt-pane-ai-rag'],
};

/** One-click fix for a setting looser than the safe defaults (B11). The server asks the person to confirm first. */
export async function applySecurityFix(fixId, btn = null) {
  if (!fixId) return;
  if (btn) btn.disabled = true;
  try {
    const res = await api.post(`/api/system/security-posture/fix/${encodeURIComponent(fixId)}`, {});
    showToast(res?.message || t('sec.fix_done', 'Fixed.'), 'success');
    await fetchAndRenderSecurityPosture();
  } catch (err) {
    if (err?.error === 'cancelled') return; // the person chose not to apply it
    showToast(t('sec.fix_failed', 'That fix did not apply: {error}', { error: err?.message || '' }), 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

export async function fetchAndRenderSecurityPosture() {
  import('./mfa-policy.js').then((m) => m.renderMfaPolicy()).catch(() => {});
  import('./malware-scan.js').then((m) => m.renderMalwareScan()).catch(() => {}); // NFEAT-11
  const badge = document.getElementById('sec-advisor-score-badge');
  const container = document.getElementById('sec-advisor-items');
  if (!badge && !container) return;

  try {
    const data = await api.get('/api/system/security-posture');
    if (!data) return;

    if (badge) {
      badge.textContent = t('sec.score_grade', 'Score: {score}/100 (grade {grade})', { score: data.score, grade: data.grade });
      if (data.score >= 90) {
        badge.style.background = 'rgba(51,205,184,0.15)';
        badge.style.color = 'var(--lt-t-33cdb8ff, #33cdb8)';
        badge.style.borderColor = 'rgba(51,205,184,0.3)';
      } else if (data.score >= 75) {
        badge.style.background = 'rgba(79,216,196,0.15)';
        badge.style.color = 'var(--kb-text-accent)';
        badge.style.borderColor = 'rgba(79,216,196,0.3)';
      } else if (data.score >= 50) {
        badge.style.background = 'rgba(234,179,8,0.15)';
        badge.style.color = 'var(--lt-t-eab308ff, #eab308)';
        badge.style.borderColor = 'rgba(234,179,8,0.3)';
      } else {
        badge.style.background = 'rgba(239,68,68,0.15)';
        badge.style.color = 'var(--lt-t-ef4444ff, #ef4444)';
        badge.style.borderColor = 'rgba(239,68,68,0.3)';
      }
    }

    if (container && Array.isArray(data.checks)) {
      container.innerHTML = data.checks.map(c => {
        const state = checkState(c);
        const passIcon = { ok: '✔', tip: 'ℹ', look: '✖' }[state];
        const passColor = { ok: 'var(--lt-t-22c55eff, #22c55e)', tip: 'var(--kb-text-muted)', look: 'var(--lt-t-ef4444ff, #ef4444)' }[state];
        const badgeBg = c.passed ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)';
        const actionText = c.passed ? t('sec.action_review', 'Review ➔') : t('sec.action_configure', 'Configure ➔');
        return `
          <div class="sec-advisor-item ${c.passed ? 'passed' : 'needs-action'}" data-check-id="${escapeHtml(c.id)}" style="background:${badgeBg}; border:1px solid ${c.passed ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.3)'};">
            <div style="display:flex; align-items:center; gap:10px; flex:1; min-width:0;">
              <span class="sec-advisor-item-icon" style="color:${passColor}; font-weight:800; font-size: var(--kb-fs-sm); line-height:1;">${passIcon}</span>
              <div style="min-width:0;">
                <div style="font-weight:600; color:var(--lt-t-f5f9f9ff, #f5f9f9); font-size: var(--kb-fs-sm); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(checkName(c))}</div>
                <div style="font-size: var(--kb-fs-xs); color:${c.passed ? 'var(--kb-text-muted)' : 'var(--lt-t-fca5a5ff, #fca5a5)'}; margin-top:2px;">${escapeHtml(checkDetails(c))}</div>
              </div>
            </div>
            <div style="display:flex; align-items:center; gap:8px; flex-shrink:0;">
              <span class="sec-advisor-status-badge" style="font-size: var(--kb-fs-xs); font-weight:700; color:${passColor}; text-transform:uppercase; letter-spacing:0.5px;">${escapeHtml(STATE_WORD[state]())}</span>
              ${c.fix ? `<button type="button" class="sec-advisor-fix-btn btn btn-sm" data-fix="${escapeHtml(c.fix)}">${escapeHtml(t(`sec.fix.${c.fix}`, c.fix_label || t('sec.fix_btn', 'Fix it')))}</button>` : ''}
              <button type="button" class="sec-advisor-action-pill" aria-label="${escapeHtml(`${actionText.replace(/\s*[➔→]\s*$/, '')}: ${checkName(c)}`)}">${escapeHtml(actionText)}</button>
            </div>
          </div>
        `;
      }).join('');

      container.querySelectorAll('.sec-advisor-fix-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          applySecurityFix(btn.dataset.fix, btn);
        });
      });

      // a row is not a button around buttons (screen readers lose the inner ones, SET-14): its
      // "Review" / "Configure" is a real button, and a click anywhere else on the row does the same
      container.querySelectorAll('.sec-advisor-item').forEach(item => {
        const checkId = item.dataset.checkId;
        item.addEventListener('click', () => handleSecurityAdvisorClick(checkId));
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
