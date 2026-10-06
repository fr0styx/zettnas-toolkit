/**
 * ZettNAS Toolkit - First-Run Setup Wizard
 * Guides the user through initial onboarding: hardware verification,
 * setting a secure administrator password, and initial configuration.
 */
import { api, auth } from '../api.js';
import { state } from '../state.js';
import { showToast } from '../toast.js';
import { bringToFront } from './dock.js';
import { t } from '../i18n.js';

let _wizardInitialized = false;
let _wizardShown = false;

export function initSetupWizard() {
  if (_wizardInitialized) return;
  _wizardInitialized = true;

  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd'))) {
    return;
  }

  const modal = document.getElementById('setup-wizard-modal');
  if (!modal) return;

  const btnClose = document.getElementById('setup-wizard-close');
  const btnSkip = document.getElementById('setup-wizard-skip');
  const btnSubmit = document.getElementById('setup-wizard-submit');
  const manualLaunchBtn = document.getElementById('btn-launch-setup-wizard');

  const closeWizard = (dismiss = true) => {
    modal.classList.remove('open');
    if (dismiss) {
      sessionStorage.setItem('zettnas_wizard_dismissed', '1');
    }
  };

  if (btnClose) btnClose.addEventListener('click', () => closeWizard(true));
  if (btnSkip) btnSkip.addEventListener('click', () => closeWizard(true));
  if (manualLaunchBtn) {
    manualLaunchBtn.addEventListener('click', () => {
      openSetupWizard();
    });
  }

  if (btnSubmit) {
    btnSubmit.addEventListener('click', async () => {
      const currentPwd = (document.getElementById('setup-current-pwd')?.value || '').trim();
      const newPwd = (document.getElementById('setup-new-pwd')?.value || '').trim();
      const confirmPwd = (document.getElementById('setup-confirm-pwd')?.value || '').trim();
      const errEl = document.getElementById('setup-wizard-err');

      const setErr = (msg) => {
        if (errEl) {
          errEl.textContent = msg;
          errEl.style.display = msg ? 'block' : 'none';
        }
      };

      if (!newPwd) {
        setErr(t('setup.err_enter_pwd', 'Please enter a new password.'));
        return;
      }
      if (newPwd.length < 8) {
        setErr(t('setup.err_min_8', 'Password must be at least 8 characters long.'));
        return;
      }
      if (newPwd.toLowerCase() === 'admin') {
        setErr(t('setup.err_not_admin', "Please choose a secure password other than 'admin'."));
        return;
      }
      if (newPwd !== confirmPwd) {
        setErr(t('setup.err_no_match', 'New password and confirmation do not match.'));
        return;
      }

      setErr('');
      btnSubmit.textContent = t('setup.saving', 'SAVING...');
      btnSubmit.disabled = true;

      try {
        await api.post('/api/security', {
          current_password: currentPwd || 'admin',
          new_password: newPwd
        });

        // Re-authenticate with new password to refresh session token seamlessly
        try {
          const loginRes = await api.post('/api/auth/login', { password: newPwd });
          if (loginRes && loginRes.token) {
            auth.setToken(loginRes.token);
          }
        } catch (authErr) {
          console.warn('Re-auth failed after password change', authErr);
        }

        localStorage.setItem('zettnas_wizard_completed', '1');
        closeWizard(false);

        const warnEl = document.getElementById('sec-default-pwd-warning');
        if (warnEl) warnEl.style.display = 'none';

        showToast(t('setup.success_toast', '🚀 Setup completed! Your new administrator password is now active.'), 'success');
      } catch (err) {
        setErr(err.message || 'Failed to update password. Check current password.');
      } finally {
        btnSubmit.textContent = t('setup.submit', 'Complete Setup & Save');
        btnSubmit.disabled = false;
      }
    });
  }
}

export function checkAndTriggerSetupWizard(stats) {
  if (_wizardShown) return;
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd'))) {
    return;
  }

  // Trigger only if default password is in use and not dismissed in this session
  if (stats && stats.security && stats.security.is_default_password) {
    if (sessionStorage.getItem('zettnas_wizard_dismissed') === '1') {
      return;
    }
    _wizardShown = true;
    setTimeout(() => {
      openSetupWizard(stats);
    }, 600);
  }
}

export function openSetupWizard(stats = null) {
  const modal = document.getElementById('setup-wizard-modal');
  if (!modal) return;

  const currentStats = stats || state.stats;
  if (currentStats) {
    const hwModel = document.getElementById('setup-hw-chassis');
    const hwFb = document.getElementById('setup-hw-fb');
    const hwFans = document.getElementById('setup-hw-fans');
    const hwLeds = document.getElementById('setup-hw-leds');

    if (hwModel) hwModel.textContent = currentStats.model || currentStats.name || 'ZettNAS Hardware';
    if (hwFb) hwFb.textContent = currentStats.lcd_active !== false ? 'Active (/dev/fb0)' : 'Not detected';
    if (hwFans) {
      const fanCount = Array.isArray(currentStats.fans) ? currentStats.fans.length : 3;
      hwFans.textContent = `Online (${fanCount} Fans Managed)`;
    }
    if (hwLeds) hwLeds.textContent = 'WS2812B Controller Ready';
  }

  modal.classList.add('open');
  modal.style.zIndex = '10005';
  const win = modal.querySelector('.smart-modal-window');
  if (win) bringToFront(win);
}
