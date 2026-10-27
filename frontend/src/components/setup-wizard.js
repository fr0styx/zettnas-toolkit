/**
 * ZettNAS Toolkit - First-Run Setup Wizard
 * Guides the user through initial onboarding: hardware verification,
 * setting a secure administrator password, host operating role,
 * UPS detection, and notification channels.
 */
import { grantShares } from './share-access.js';
import { onManagementDom } from '../management-dom.js';
import { api, auth } from '../api.js';
import { state } from '../state.js';
import { showToast } from '../toast.js';
import { bringToFront } from './dock.js';
import { t } from '../i18n.js';

let _wizardInitialized = false;
let _wizardShown = false;

function setWizardError(msg, step = 2) {
  const errEl = document.getElementById('setup-wizard-err');
  if (errEl) {
    // the message sits under the step that has the problem
    const home = step === 2
      ? document.getElementById('setup-confirm-pwd')?.closest('[data-setup-step]')
      : document.querySelector(`#setup-wizard-modal [data-setup-step="${step}"]`);
    if (msg && home && !home.contains(errEl)) home.appendChild(errEl);
    errEl.textContent = msg;
    errEl.style.display = msg ? 'block' : 'none';
  }
}

/** The server's name in the browser tab (UX-17). */
export function applyServerName(name) {
  const clean = String(name || '').trim();
  document.title = clean ? `${clean} · ZettNAS` : 'ZettNAS';
  const drawer = document.getElementById('drawer-nas-name');
  if (drawer && clean) drawer.textContent = clean;
}

let _identityLoaded = false;
async function loadIdentity() {
  if (_identityLoaded) return null;
  _identityLoaded = true;
  try {
    const id = await api.get('/api/system/identity');
    applyServerName(id?.server_name);
    const nameInput = document.getElementById('setup-server-name');
    if (nameInput && id?.server_name && !nameInput.value) nameInput.value = id.server_name;
    fillTimezones(document.getElementById('setup-timezone'), id?.timezone || '');
    return id;
  } catch {
    _identityLoaded = false;
    return null;
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

/** The people step's problem, or '' (UX-17: a person is optional, but needs a password). */
export function personStepProblem() {
  const name = (document.getElementById('setup-person-name')?.value || '').trim();
  const pwd = document.getElementById('setup-person-pwd')?.value || '';
  if (!name) return '';
  if (!/^[a-zA-Z0-9_-][a-zA-Z0-9_.-]{1,31}$/.test(name)) return t('setup.err_person_name', 'Use 2 to 32 letters, numbers, dots, dashes or underscores for the user name.');
  if (pwd.length < 8) return t('setup.err_person_pwd', 'Their password needs at least 8 characters.');
  return '';
}

/** The time zones to choose from, the server's (or this browser's) first. */
export function fillTimezones(select, current = '') {
  if (!select || select.options.length) return;
  let zones;
  try {
    zones = Intl.supportedValuesOf('timeZone');
  } catch {
    zones = ['UTC'];
  }
  const browser = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const chosen = current || browser;
  if (!zones.includes(chosen)) zones = [chosen, ...zones];
  select.innerHTML = zones.map((z) => `<option value="${z}"${z === chosen ? ' selected' : ''}>${z.replace(/_/g, ' ')}</option>`).join('');
}

/** Step 3 and 4: what the storage is, and whether ZettNAS or the host makes shares. */
export async function loadStorageStep() {
  const info = document.getElementById('setup-storage-info');
  const shareHost = document.getElementById('setup-share-host');
  const shareForm = document.getElementById('setup-share-form');
  try {
    const [platform, pools] = await Promise.all([api.get('/api/storage/platform'), api.get('/api/storage/pools').catch(() => ({}))]);
    const host = String(platform?.platform || '').replace(/^\w/, (c) => c.toUpperCase());
    const list = Array.isArray(pools?.pools) ? pools.pools : [];
    const observer = Boolean(platform?.capabilities?.is_observer_mode);
    if (info) {
      const names = list.map((p) => p.name || p.id).filter(Boolean).slice(0, 4).join(', ');
      info.textContent = observer
        ? t('setup.storage_host', '{host} looks after the drives and storage; ZettNAS shows and uses what it sets up.', { host })
        : list.length
          ? t('setup.storage_pools', 'Storage ready: {names}.', { names })
          : t('setup.storage_none', 'No storage pool yet. You can create one later in Storage.');
    }
    if (observer && shareHost && shareForm) {
      shareHost.hidden = false;
      shareHost.textContent = t('setup.share_host', 'Shared folders are made in {host} itself; ZettNAS lists them under Shares.', { host });
      shareForm.hidden = true;
    }
    return { observer };
  } catch {
    if (info) info.textContent = t('setup.storage_none', 'No storage pool yet. You can create one later in Storage.');
    return { observer: false };
  }
}

/**
 * Shows the wizard one step at a time (UX-17): 1 welcome and name; 2 password; 3 storage;
 * 4 a first shared folder; 5 people; 6 time zone and alerts. Blocks say their step with
 * data-setup-step; this groups them and adds Back/Next.
 */
export function initWizardStepper(modal) {
  const body = modal.querySelector('.smart-modal-body');
  const blocks = body ? Array.from(body.children) : [];
  const footer = blocks[blocks.length - 1];
  const tagged = blocks.filter((b) => b.dataset && b.dataset.setupStep);
  const groups = {};
  if (tagged.length) {
    tagged.forEach((b) => {
      (groups[b.dataset.setupStep] ||= []).push(b);
    });
  } else {
    Object.assign(groups, { 1: [blocks[0], blocks[1], blocks[3]], 2: [blocks[2]], 3: [blocks[4]] });
  }
  const last = Math.max(...Object.keys(groups).map(Number));
  const allNames = [
    t('setup.step_welcome', 'Welcome'),
    t('setup.step_password', 'Password'),
    t('setup.step_storage', 'Storage'),
    t('setup.step_share', 'Share'),
    t('setup.step_people', 'People'),
    t('setup.step_finish', 'Time & alerts'),
  ];
  const names = last === 3 ? [allNames[0], allNames[1], t('setup.step_alerts', 'Alerts')] : allNames.slice(0, last);
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
    current = Math.max(1, Math.min(last, step));
    if (current === 3 && last > 3) loadStorageStep();
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
    next.hidden = current === last;
    if (submit) submit.hidden = current !== last;
  }
  back.addEventListener('click', () => show(current - 1));
  next.addEventListener('click', () => {
    const problem = current === 2 ? passwordStepProblem() : current === 5 && last > 3 ? personStepProblem() : '';
    setWizardError(problem, current);
    if (problem) return;
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
      const firstRun = isPasswordDefault();
      btnSubmit.textContent = t('setup.saving', 'Saving...');
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

        // 3. The server's name and time zone, a first shared folder, another person (UX-17)
        await saveSetupExtras();

        // 4. Save Notification Webhook if provided (needs the new session)
        const notifUrl = (document.getElementById('setup-notif-url')?.value || '').trim();
        if (notifUrl) {
          try {
            // REL-6: add to the saved settings (secrets stay masked and kept), then send a test alert
            const current = (await api.get('/api/notifications/config').catch(() => null)) || {};
            const urls = Array.isArray(current.apprise_urls) ? current.apprise_urls : [];
            await api.post('/api/notifications/config', {
              ...current,
              enabled: true,
              apprise_urls: urls.includes(notifUrl) ? urls : [...urls, notifUrl],
            });
            api.post('/api/notifications/test', {}).catch(() => null);
          } catch (notifErr) {
            console.warn('[SetupWizard] Failed to save notification URL:', notifErr);
          }
        }

        localStorage.setItem('zettnas_wizard_completed', '1');
        // a new owner starts with the everyday places; Advanced is one switch away (UX-2)
        if (firstRun) localStorage.setItem('zettnas_advanced', '0');
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

/** Saves the optional steps; each one that fails says so and the rest still happen. */
export async function saveSetupExtras() {
  const name = document.getElementById('setup-server-name')?.value?.trim() || '';
  const tz = document.getElementById('setup-timezone')?.value || '';
  if (name || tz) {
    try {
      const id = await api.put('/api/system/identity', { server_name: name, timezone: tz || null });
      applyServerName(id?.server_name ?? name);
    } catch (err) {
      showToast(t('setup.err_identity', 'The name and time zone were not saved: {error}', { error: err.message }), 'warning');
    }
  }
  const shareForm = document.getElementById('setup-share-form');
  const shareName = document.getElementById('setup-share-name')?.value?.trim() || '';
  let sharedFolder = '';
  if (shareForm && !shareForm.hidden && document.getElementById('setup-share-create')?.checked && shareName) {
    try {
      await api.post('/api/storage/shares', { name: shareName, security: 'private' });
      sharedFolder = shareName;
    } catch (err) {
      showToast(t('setup.err_share', 'The shared folder was not created: {error}', { error: err.message }), 'warning');
    }
  }
  const person = document.getElementById('setup-person-name')?.value?.trim() || '';
  if (person && !personStepProblem()) {
    try {
      await api.post('/api/users', {
        username: person,
        password: document.getElementById('setup-person-pwd')?.value || '',
        role_id: document.getElementById('setup-person-role')?.value || 'share_user',
      });
      if (sharedFolder) await grantFolder(sharedFolder, person);
    } catch (err) {
      showToast(t('setup.err_person', '{name} was not added: {error}', { name: person, error: err.message }), 'warning');
    }
  }
}

/** New installs give nobody a folder by default, so the person the wizard adds gets the folder it made. */
export async function grantFolder(share, person) {
  try {
    await grantShares(person, { [share]: 'write' });
  } catch (err) {
    showToast(t('setup.err_grant', '{name} was added but cannot open {share} yet: {error}', { name: person, share, error: err.message }), 'warning');
  }
}

export function checkAndTriggerSetupWizard(stats) {
  loadIdentity();
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
      hwFb.textContent = fbActive ? t('setup.hw_screen_on', 'Working') : t('setup.hw_screen_none', 'None found (that is fine)');
      hwFb.title = fbActive ? '/dev/fb0' : t('ui.no_framebuffer_device_detected_at', 'No framebuffer device detected at /dev/fb0.');
      hwFb.style.color = fbActive ? 'var(--ok2)' : 'var(--muted)';
    }

    if (hwFans) {
      const fanList = Array.isArray(currentStats.fans) ? currentStats.fans : [];
      const spinningCount = fanList.filter(r => r > 0).length;
      if (spinningCount > 0) {
        hwFans.textContent = t('setup.hw_fans_on', '{n} of {total} fans running', { n: spinningCount, total: fanList.length });
        hwFans.style.color = 'var(--ok2)';
      } else if (fanList.length > 0) {
        hwFans.textContent = t('setup.hw_fans_idle', '{total} fans, all stopped for now', { total: fanList.length });
        hwFans.style.color = 'var(--warn)';
      } else {
        hwFans.textContent = t('setup.hw_fans_unknown', 'Fan speeds cannot be read on this machine');
        hwFans.style.color = 'var(--muted)';
      }
    }

    if (hwLeds) {
      const ledReady = currentStats?.peripherals?.led_ready;
      const ledPort = currentStats?.peripherals?.led_port;
      if (ledReady) {
        hwLeds.textContent = t('setup.hw_screen_on', 'Working');
        hwLeds.title = `WS2812B (${ledPort || 'serial'})`;
        hwLeds.style.color = 'var(--ok2)';
      } else {
        hwLeds.textContent = t('setup.hw_leds_none', 'None found');
        hwLeds.title = t('ui.ws2812b_controller_not_detected', 'WS2812B Controller Not Detected');
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

  fillTimezones(document.getElementById('setup-timezone'));
  modal.classList.add('open');
  modal.style.zIndex = 'var(--z-modal, 9100)';
  const win = modal.querySelector('.smart-modal-window');
  if (win) bringToFront(win);
}
