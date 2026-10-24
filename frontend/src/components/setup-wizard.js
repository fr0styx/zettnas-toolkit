/**
 * ZettNAS Toolkit - First-Run Setup Wizard
 * Guides the user through initial onboarding: hardware verification,
 * setting a secure administrator password, host operating role,
 * UPS detection, and notification channels.
 */
import { onManagementDom } from '../management-dom.js';
import { api, auth } from '../api.js';
import { state } from '../state.js';
import { showToast } from '../toast.js';
import { bringToFront } from './dock.js';
import { t } from '../i18n.js';

let _wizardInitialized = false;
let _wizardShown = false;

function setWizardError(msg) {
  const errEl = document.getElementById('setup-wizard-err');
  if (errEl) {
    errEl.textContent = msg;
    errEl.style.display = msg ? 'block' : 'none';
  }
}

/** The password step's problem, or '' when it can be submitted. */
export function passwordStepProblem() {
  const currentPwd = (document.getElementById('setup-current-pwd')?.value || '').trim();
  const newPwd = (document.getElementById('setup-new-pwd')?.value || '').trim();
  const confirmPwd = (document.getElementById('setup-confirm-pwd')?.value || '').trim();
  if (!currentPwd) return t('setup.err_enter_current', 'Please enter your current password.');
  if (!newPwd) return t('setup.err_enter_pwd', 'Please enter a new password.');
  if (newPwd.length < 8) return t('setup.err_min_8', 'Password must be at least 8 characters long.');
  if (newPwd.toLowerCase() === 'admin') return t('setup.err_not_admin', "Please choose a secure password other than 'admin'.");
  if (newPwd !== confirmPwd) return t('setup.err_no_match', 'New password and confirmation do not match.');
  return '';
}

/**
 * Shows the wizard one step at a time (UX-1): 1 welcome, hardware and power; 2 password;
 * 3 alerts. The body's blocks keep their markup; this groups them and adds Back/Next.
 */
export function initWizardStepper(modal) {
  const body = modal.querySelector('.smart-modal-body');
  const blocks = body ? Array.from(body.children) : [];
  const footer = blocks[blocks.length - 1];
  const groups = { 1: [blocks[0], blocks[1], blocks[3]], 2: [blocks[2]], 3: [blocks[4]] };
  const names = [t('setup.step_welcome', 'Welcome'), t('setup.step_password', 'Password'), t('setup.step_alerts', 'Alerts')];
  let current = 1;
  const steps = document.createElement('ol');
  steps.className = 'setup-steps';
  steps.setAttribute('aria-label', t('setup.steps_label', 'Setup steps'));
  steps.innerHTML = names.map((n, i) => `<li data-step="${i + 1}">${n}</li>`).join('');
  if (body) body.insertBefore(steps, body.firstChild);
  const back = document.createElement('button');
  back.type = 'button';
  back.className = 'btn-pill-toggle setup-step-nav';
  back.id = 'setup-wizard-back';
  back.textContent = t('setup.back', 'Back');
  const next = document.createElement('button');
  next.type = 'button';
  next.className = 'btn-pill-toggle is-primary setup-step-nav';
  next.id = 'setup-wizard-next';
  next.textContent = t('setup.next', 'Next');
  const submit = document.getElementById('setup-wizard-submit');
  if (footer && submit) {
    footer.insertBefore(back, submit);
    footer.insertBefore(next, submit);
  }
  function show(step) {
    current = Math.max(1, Math.min(3, step));
    for (const [n, els] of Object.entries(groups)) {
      els.forEach((el) => {
        if (el) el.hidden = Number(n) !== current;
      });
    }
    steps.querySelectorAll('li').forEach((li) => {
      const n = Number(li.dataset.step);
      li.classList.toggle('is-current', n === current);
      li.classList.toggle('is-done', n < current);
      if (n === current) li.setAttribute('aria-current', 'step');
      else li.removeAttribute('aria-current');
    });
    back.hidden = current === 1;
    next.hidden = current === 3;
    if (submit) submit.hidden = current !== 3;
  }
  back.addEventListener('click', () => show(current - 1));
  next.addEventListener('click', () => {
    if (current === 2) {
      const problem = passwordStepProblem();
      setWizardError(problem);
      if (problem) return;
    }
    show(current + 1);
  });
  show(1);
  return { show, get current() { return current; } };
}

export function initSetupWizard() {
  window.openSetupWizard = openSetupWizard;
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

  const isPasswordDefault = () => {
    const s = state.stats || state.latestStats;
    return s?.security?.is_default_password === true;
  };

  const closeWizard = (dismiss = true) => {
    if (dismiss && isPasswordDefault()) {
      showToast(t('setup.cannot_dismiss', 'Security Setup Required: Please configure a new administrator password before continuing.'), 'warning');
      return;
    }
    modal.classList.remove('open');
    if (dismiss) {
      sessionStorage.setItem('zettnas_wizard_dismissed', '1');
    }
  };

  if (btnClose) btnClose.addEventListener('click', () => closeWizard(true));
  if (btnSkip) btnSkip.addEventListener('click', () => closeWizard(true));
  onManagementDom(() => {
    const manualLaunchBtn = document.getElementById('btn-launch-setup-wizard');
    if (manualLaunchBtn) {
      manualLaunchBtn.addEventListener('click', () => {
        openSetupWizard(null, true);
      });
    }
  });

  // Prevent backdrop clicks from bypassing setup when default password is in use
  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      closeWizard(true);
    }
  });

  // Guard Escape key when password is required
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal.classList.contains('open')) {
      if (isPasswordDefault()) {
        e.preventDefault();
        e.stopPropagation();
        showToast(t('setup.cannot_dismiss', 'Security Setup Required: Please configure a new administrator password before continuing.'), 'warning');
      } else {
        closeWizard(true);
      }
    }
  }, true);

  const stepper = initWizardStepper(modal);

  if (btnSubmit) {
    btnSubmit.addEventListener('click', async () => {
      const currentPwd = (document.getElementById('setup-current-pwd')?.value || '').trim();
      const newPwd = (document.getElementById('setup-new-pwd')?.value || '').trim();
      const setErr = setWizardError;
      const problem = passwordStepProblem();
      if (problem) {
        setErr(problem);
        stepper.show(2);
        return;
      }

      setErr('');
      btnSubmit.textContent = t('setup.saving', 'SAVING...');
      btnSubmit.disabled = true;

      try {
        // 1. Update password. The server only lets this session change its
        // password until it has done so (SEC-23).
        let me = null;
        try {
          me = await api.get('/api/auth/me');
        } catch (meErr) {
          console.warn('[SetupWizard] Could not load the current user', meErr);
        }
        if (me && me.role && me.role !== 'superadmin') {
          await api.post(`/api/users/${encodeURIComponent(me.id)}/password`, {
            current_password: currentPwd,
            new_password: newPwd
          });
        } else {
          await api.post('/api/security', {
            current_password: currentPwd,
            new_password: newPwd
          });
        }

        // 2. Re-authenticate with the new password: the change signed this session out.
        try {
          const loginBody = me?.username ? { username: me.username, password: newPwd } : { password: newPwd };
          const loginRes = await api.post('/api/auth/login', loginBody);
          if (loginRes && loginRes.token) {
            auth.setToken(loginRes.token);
          }
        } catch (authErr) {
          console.warn('[SetupWizard] Re-auth failed after password change', authErr);
        }

        // 3. Save Notification Webhook if provided (needs the new session)
        const notifUrl = (document.getElementById('setup-notif-url')?.value || '').trim();
        if (notifUrl) {
          try {
            await api.post('/api/notifications/config', {
              urls: [notifUrl],
              enabled: true
            });
          } catch (notifErr) {
            console.warn('[SetupWizard] Failed to save notification URL:', notifErr);
          }
        }

        localStorage.setItem('zettnas_wizard_completed', '1');
        if (state.stats?.security) {
          state.stats.security.is_default_password = false;
        }
        if (state.latestStats?.security) {
          state.latestStats.security.is_default_password = false;
        }

        closeWizard(false);

        const warnEl = document.getElementById('sec-default-pwd-warning');
        if (warnEl) warnEl.style.display = 'none';

        showToast(t('setup.success_toast', '🚀 Setup completed! Your new administrator password is now active.'), 'success');
        if (typeof window.openGettingStarted === 'function') window.openGettingStarted();
      } catch (err) {
        setErr(err.message || 'Failed to update password. Check current password.');
        stepper.show(2);
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

  // Trigger if default password is in use and not dismissed in this session
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

export function openSetupWizard(stats = null, forced = false) {
  const modal = document.getElementById('setup-wizard-modal');
  if (!modal) return;

  const currentStats = stats || state.stats || state.latestStats;
  const isDefaultPwd = forced ? false : (currentStats?.security?.is_default_password === true);
  const skipBtn = document.getElementById('setup-wizard-skip');
  const closeBtn = document.getElementById('setup-wizard-close');

  if (isDefaultPwd) {
    if (skipBtn) skipBtn.style.display = 'none';
    if (closeBtn) closeBtn.style.display = 'none';
  } else {
    if (skipBtn) skipBtn.style.display = 'inline-block';
    if (closeBtn) {
      closeBtn.style.display = 'inline-block';
      closeBtn.title = t('ui.close_dialog', 'Close dialog');
    }
  }

  if (currentStats) {
    const hwModel = document.getElementById('setup-hw-chassis');
    const hwFb = document.getElementById('setup-hw-fb');
    const hwFans = document.getElementById('setup-hw-fans');
    const hwLeds = document.getElementById('setup-hw-leds');
    if (hwModel) {
      const friendlyName = currentStats.chassis_label || (
        currentStats.chassis === 'd4' ? 'Zettlab D4 (4-Bay)' :
        currentStats.chassis === 'd6u' ? 'Zettlab D6 Ultra (6-Bay)' :
        currentStats.chassis === 'd8u' ? 'Zettlab D8 Ultra (8-Bay)' :
        (currentStats.chassis ? String(currentStats.chassis).toUpperCase() : (currentStats.model || currentStats.name || 'ZettNAS Hardware'))
      );
      hwModel.textContent = friendlyName;
    }

    if (hwFb) {
      const fbActive = currentStats?.peripherals?.fb_active ?? (currentStats?.lcd_active && currentStats?.lcd?.page !== undefined);
      hwFb.textContent = fbActive ? 'Active (/dev/fb0)' : 'Not detected (Headless)';
      hwFb.style.color = fbActive ? 'var(--ok2)' : 'var(--muted)';
    }

    if (hwFans) {
      const fanList = Array.isArray(currentStats.fans) ? currentStats.fans : [];
      const spinningCount = fanList.filter(r => r > 0).length;
      if (spinningCount > 0) {
        hwFans.textContent = `Online (${spinningCount}/${fanList.length} Fans Spinning)`;
        hwFans.style.color = 'var(--ok2)';
      } else if (fanList.length > 0) {
        hwFans.textContent = `Managed (${fanList.length} Fans Idle / 0 RPM)`;
        hwFans.style.color = 'var(--warn)';
      } else {
        hwFans.textContent = t('ui.hardware_tachometers_unavailable', 'Hardware tachometers unavailable');
        hwFans.style.color = 'var(--muted)';
      }
    }

    if (hwLeds) {
      const ledReady = currentStats?.peripherals?.led_ready;
      const ledPort = currentStats?.peripherals?.led_port;
      if (ledReady) {
        hwLeds.textContent = `WS2812B Controller Online (${ledPort || 'Serial'})`;
        hwLeds.style.color = 'var(--ok2)';
      } else {
        hwLeds.textContent = t('ui.ws2812b_controller_not_detected', 'WS2812B Controller Not Detected');
        hwLeds.style.color = 'var(--muted)';
      }
    }

    // UPS Status
    const upsBadge = document.getElementById('setup-ups-badge');
    const upsText = document.getElementById('setup-ups-text');
    if (upsBadge && upsText) {
      const ups = currentStats?.ups;
      const isOnline = ups && (ups.status === 'OL' || ups.status === 'online' || (ups.battery_charge && ups.battery_charge > 0));
      if (isOnline) {
        upsBadge.style.background = 'var(--ok2, #4ade80)';
        upsText.textContent = `${t('setup.ups_detected', 'UPS Online & Monitored')} (${ups.model || ups.ups_name || 'NUT'}) - ${ups.battery_charge || 100}%`;
        upsText.style.color = 'var(--ok2, #4ade80)';
      } else {
        upsBadge.style.background = 'var(--muted, #64748b)';
        upsText.textContent = t('setup.ups_none', 'No UPS detected. You can configure a NUT host later in Settings.');
        upsText.style.color = 'var(--muted, #94a3b8)';
      }
    }
  }

  modal.classList.add('open');
  modal.style.zIndex = 'var(--z-modal, 9100)';
  const win = modal.querySelector('.smart-modal-window');
  if (win) bringToFront(win);
}
