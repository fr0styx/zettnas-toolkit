/**
 * ZettNAS Toolkit Authentication & Lock Screen Component
 * Handles Dual-Mode Login, MFA/TOTP Challenge Interception, and Inactivity Auto-Lock.
 */
import { auth } from '../api.js';
import { ZettEventBus } from '../event-bus.js';
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';
import { fetchCurrentProfile, getCurrentUser, setCurrentUser } from './users.js';

let _pendingMfaToken = null;
let _selectedUser = null;
let _autoLockTimer = null;
let _isLocked = false;
let _clockInterval = null;

const DEFAULT_IDLE_TIMEOUT_MS = 15 * 60 * 1000; // 15 minutes default

export function isDesktopLocked() {
  return _isLocked;
}

export function initAuth() {
  const overlay = document.getElementById('login-overlay');
  const dock = document.getElementById('os-dock-container');
  const loginBtn = document.getElementById('login-btn');
  const loginPwd = document.getElementById('login-password');
  const loginUser = document.getElementById('login-username');
  const rememberMe = document.getElementById('login-remember-me');

  // Handle auth:required
  ZettEventBus.on('auth:required', () => {
    document.documentElement.classList.remove('has-auth-session');
    document.documentElement.classList.add('auth-required');
    if (overlay) {
      overlay.style.removeProperty('opacity');
      overlay.style.display = 'flex';
      renderLoginChooser();
    }
    if (dock) dock.style.display = 'none';
  });

  // Handle auth:login
  ZettEventBus.on('auth:login', () => {
    fetchCurrentProfile();
    resetInactivityTimer();
  });

  // Dual-mode toggle links
  const btnToggleManual = document.getElementById('login-toggle-manual');
  if (btnToggleManual) {
    btnToggleManual.addEventListener('click', (e) => {
      e.preventDefault();
      setLoginMode('manual');
      if (loginUser) {
        loginUser.value = '';
        loginUser.focus();
      }
    });
  }

  // Selected user card click / change account handlers
  const userSelectedCard = document.getElementById('login-user-selected-card');
  const changeUserBtn = document.getElementById('login-change-user-btn');

  const triggerChangeUser = (e) => {
    if (e) e.preventDefault();
    const chooserContainer = document.getElementById('login-users-chooser');
    const cards = chooserContainer ? chooserContainer.querySelectorAll('.login-user-card') : [];
    if (cards.length > 1) {
      setLoginMode('chooser');
    } else {
      setLoginMode('manual');
      if (loginUser) {
        loginUser.value = '';
        loginUser.focus();
      }
    }
  };

  if (userSelectedCard) {
    userSelectedCard.addEventListener('click', triggerChangeUser);
    userSelectedCard.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        triggerChangeUser(e);
      }
    });
    userSelectedCard.addEventListener('mouseenter', () => {
      userSelectedCard.style.background = 'rgba(14,165,233,0.18)';
      userSelectedCard.style.borderColor = 'rgba(56,189,248,0.5)';
    });
    userSelectedCard.addEventListener('mouseleave', () => {
      userSelectedCard.style.background = 'rgba(14,165,233,0.1)';
      userSelectedCard.style.borderColor = 'rgba(56,189,248,0.3)';
    });
  }
  if (changeUserBtn) {
    changeUserBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      triggerChangeUser(e);
    });
  }

  const btnToggleChooser = document.getElementById('login-toggle-chooser');
  if (btnToggleChooser) {
    btnToggleChooser.addEventListener('click', (e) => {
      e.preventDefault();
      setLoginMode('chooser');
    });
  }

  // 2FA Challenge submit
  const mfaForm = document.getElementById('form-mfa-challenge');
  if (mfaForm) {
    mfaForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      await submitMfaChallenge();
    });
  }

  const btnToggleRecovery = document.getElementById('mfa-toggle-recovery');
  if (btnToggleRecovery) {
    btnToggleRecovery.addEventListener('click', (e) => {
      e.preventDefault();
      const codeInput = document.getElementById('mfa-challenge-code');
      const isRecovery = codeInput.placeholder.includes('Recovery');
      if (isRecovery) {
        codeInput.placeholder = '6-Digit Code (e.g. 123456)';
        codeInput.maxLength = 6;
        btnToggleRecovery.textContent = 'Use 8-character recovery code';
      } else {
        codeInput.placeholder = '8-Char Recovery Code (xxxx-xxxx)';
        codeInput.maxLength = 10;
        btnToggleRecovery.textContent = 'Use 6-digit authenticator code';
      }
      codeInput.value = '';
      codeInput.focus();
    });
  }

  const btnBackToLogin = document.getElementById('mfa-back-btn');
  if (btnBackToLogin) {
    btnBackToLogin.addEventListener('click', (e) => {
      e.preventDefault();
      _pendingMfaToken = null;
      document.getElementById('login-step-credentials').style.display = 'block';
      document.getElementById('login-step-mfa').style.display = 'none';
    });
  }

  // Login form submit
  if (loginBtn) {
    loginBtn.addEventListener('click', () => doLogin());
  }
  if (loginPwd) {
    loginPwd.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') doLogin();
    });
  }
  if (loginUser) {
    loginUser.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        if (loginPwd) loginPwd.focus();
      }
    });
  }

  // Initialize Lock Overlay
  initLockOverlay();

  // Initialize Inactivity Tracker
  initInactivityTracker();

  // Enforce lock if persisted in sessionStorage
  if (sessionStorage.getItem('zettnas_desktop_locked') === 'true') {
    lockDesktop();
  }

  // Intercept browser back/forward and bfcache navigation while locked
  window.addEventListener('popstate', () => {
    if (sessionStorage.getItem('zettnas_desktop_locked') === 'true' || _isLocked) {
      lockDesktop();
    }
  });

  window.addEventListener('pageshow', () => {
    if (sessionStorage.getItem('zettnas_desktop_locked') === 'true' || _isLocked) {
      lockDesktop();
    }
  });

  // Try fetching current profile if we have active session
  fetchCurrentProfile();
}

export async function renderLoginChooser(options = {}) {
  const { forceChooser = false } = options;
  const chooserContainer = document.getElementById('login-users-chooser');
  const manualFields = document.getElementById('login-manual-fields');
  const userSelectedCard = document.getElementById('login-user-selected-card');
  const btnToggleManual = document.getElementById('login-toggle-manual');
  const btnToggleChooser = document.getElementById('login-toggle-chooser');

  if (!chooserContainer) return;

  try {
    const res = await window.fetch('/api/auth/users-list');
    if (!res.ok) throw new Error('Could not fetch user list');
    const users = await res.json();

    if (!Array.isArray(users) || users.length === 0) {
      setLoginMode('manual');
      return;
    }

    // Render user tiles
    chooserContainer.innerHTML = users.map((u) => {
      const letter = (u.display_name?.[0] || u.username?.[0] || 'U').toUpperCase();
      return `
        <div class="login-user-card" data-username="${escapeHtml(u.username)}" data-display="${escapeHtml(u.display_name || u.username)}" style="cursor:pointer; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1); border-radius:10px; padding:12px 14px; display:flex; align-items:center; gap:12px; transition:all 0.2s ease;">
          <div style="width:36px; height:36px; border-radius:50%; background:linear-gradient(135deg, #0284c7, #0369a1); display:flex; align-items:center; justify-content:center; font-weight:800; color:#fff; font-size:14px; border:1px solid rgba(255,255,255,0.2);">
            ${escapeHtml(letter)}
          </div>
          <div style="text-align:left; flex:1; min-width:0;">
            <div style="font-weight:700; color:#fff; font-size:13.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(u.display_name || u.username)}</div>
            <div style="font-size:11px; color:var(--muted);">@${escapeHtml(u.username)}</div>
          </div>
          <div style="color:var(--muted); font-size:14px;">➔</div>
        </div>
      `;
    }).join('');

    // Attach click handlers to user cards
    chooserContainer.querySelectorAll('.login-user-card').forEach((card) => {
      card.addEventListener('click', () => {
        selectUserForLogin(card.dataset.username, card.dataset.display);
      });
      card.addEventListener('mouseenter', () => {
        card.style.background = 'rgba(14,165,233,0.12)';
        card.style.borderColor = 'rgba(56,189,248,0.4)';
      });
      card.addEventListener('mouseleave', () => {
        card.style.background = 'rgba(255,255,255,0.04)';
        card.style.borderColor = 'rgba(255,255,255,0.1)';
      });
    });

    if (forceChooser) {
      if (users.length > 1) {
        setLoginMode('chooser');
      } else {
        setLoginMode('manual');
        const loginUser = document.getElementById('login-username');
        if (loginUser) {
          loginUser.value = '';
          loginUser.focus();
        }
      }
    } else {
      // Default to first user or admin if single user
      if (users.length === 1) {
        selectUserForLogin(users[0].username, users[0].display_name);
      } else {
        setLoginMode('chooser');
      }
    }

  } catch (err) {
    console.warn('[LOGIN] Fallback to manual login mode:', err);
    setLoginMode('manual');
  }
}

function selectUserForLogin(username, displayName) {
  _selectedUser = { username, displayName };
  const chooserContainer = document.getElementById('login-users-chooser');
  const userSelectedCard = document.getElementById('login-user-selected-card');
  const selectedName = document.getElementById('login-selected-name');
  const selectedInitial = document.getElementById('login-selected-initial');
  const loginUser = document.getElementById('login-username');
  const loginPwd = document.getElementById('login-password');
  const manualFields = document.getElementById('login-manual-fields');
  const btnToggleManual = document.getElementById('login-toggle-manual');

  if (loginUser) loginUser.value = username;
  if (chooserContainer) chooserContainer.style.display = 'none';
  if (manualFields) manualFields.style.display = 'none';

  if (userSelectedCard) {
    userSelectedCard.style.display = 'flex';
    if (selectedName) selectedName.textContent = displayName || username;
    if (selectedInitial) selectedInitial.textContent = (displayName?.[0] || username?.[0] || 'U').toUpperCase();
  }

  if (btnToggleManual) btnToggleManual.style.display = 'block';
  if (loginPwd) {
    loginPwd.focus();
  }
}

function setLoginMode(mode) {
  const chooserContainer = document.getElementById('login-users-chooser');
  const manualFields = document.getElementById('login-manual-fields');
  const userSelectedCard = document.getElementById('login-user-selected-card');
  const btnToggleManual = document.getElementById('login-toggle-manual');
  const btnToggleChooser = document.getElementById('login-toggle-chooser');
  const loginUser = document.getElementById('login-username');
  const loginPwd = document.getElementById('login-password');

  if (mode === 'chooser') {
    _selectedUser = null;
    if (chooserContainer) chooserContainer.style.display = 'flex';
    if (manualFields) manualFields.style.display = 'none';
    if (userSelectedCard) userSelectedCard.style.display = 'none';
    if (btnToggleManual) btnToggleManual.style.display = 'block';
    if (btnToggleChooser) btnToggleChooser.style.display = 'none';
  } else {
    // manual mode
    _selectedUser = null;
    if (chooserContainer) chooserContainer.style.display = 'none';
    if (manualFields) manualFields.style.display = 'block';
    if (userSelectedCard) userSelectedCard.style.display = 'none';
    if (btnToggleManual) btnToggleManual.style.display = 'none';
    if (btnToggleChooser) btnToggleChooser.style.display = 'block';
    if (loginUser) {
      if (!loginUser.value) loginUser.value = 'admin';
      loginUser.focus();
    }
  }
}

async function doLogin() {
  const loginBtn = document.getElementById('login-btn');
  const loginPwd = document.getElementById('login-password');
  const loginUser = document.getElementById('login-username');
  const rememberMe = document.getElementById('login-remember-me');
  const overlay = document.getElementById('login-overlay');
  const dock = document.getElementById('os-dock-container');

  if (!loginPwd) return;

  const username = _selectedUser ? _selectedUser.username : (loginUser?.value?.trim() || 'admin');
  const password = loginPwd.value;
  const isRemembered = rememberMe ? rememberMe.checked : true;

  if (loginBtn) loginBtn.textContent = t('login.authenticating', 'AUTHENTICATING...');

  try {
    const res = await window.fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username,
        password,
        remember_me: isRemembered
      }),
      credentials: 'include'
    });

    const data = await res.json();

    // Check if 2FA challenge is required
    if (res.ok && data.status === 'mfa_required' && data.mfa_token) {
      _pendingMfaToken = data.mfa_token;
      showMfaChallengeView(username);
      if (loginBtn) loginBtn.textContent = t('login.btn', 'SECURE LOGIN');
      return;
    }

    if (res.ok && (data.status === 'ok' || data.token)) {
      if (data.token) auth.setToken(data.token);
      if (data.user) setCurrentUser(data.user);

      document.documentElement.classList.remove('auth-required');
      document.documentElement.classList.add('has-auth-session');
      if (dock) dock.style.display = '';

      if (overlay) {
        overlay.style.transition = 'opacity 0.25s ease';
        overlay.style.opacity = '0';
        setTimeout(() => {
          overlay.style.display = 'none';
          overlay.style.opacity = '1';
        }, 250);
      }

      if (loginBtn) loginBtn.textContent = t('login.btn', 'SECURE LOGIN');
      loginPwd.value = '';
      ZettEventBus.emit('auth:login');
    } else {
      let msg = data.detail || t('login.invalid', 'INVALID CREDENTIALS');
      let holdMs = 2000;
      if (res.status === 429) {
        const retry = parseInt(res.headers.get('Retry-After') || '0', 10);
        msg = retry > 0 ? `TOO MANY ATTEMPTS — WAIT ${retry}s` : 'TOO MANY ATTEMPTS';
        holdMs = Math.min(Math.max(retry, 2), 15) * 1000;
      }
      if (loginBtn) {
        loginBtn.textContent = msg;
        loginBtn.style.borderColor = 'var(--crit)';
        setTimeout(() => {
          loginBtn.textContent = t('login.btn', 'SECURE LOGIN');
          loginBtn.style.borderColor = '';
        }, holdMs);
      }
    }
  } catch (e) {
    if (loginBtn) loginBtn.textContent = t('login.error', 'ERROR');
  }
}

function showMfaChallengeView(username) {
  const credsStep = document.getElementById('login-step-credentials');
  const mfaStep = document.getElementById('login-step-mfa');
  const mfaUserTxt = document.getElementById('mfa-user-target');
  const codeInput = document.getElementById('mfa-challenge-code');

  if (credsStep) credsStep.style.display = 'none';
  if (mfaStep) mfaStep.style.display = 'block';
  if (mfaUserTxt) mfaUserTxt.textContent = `Authenticating @${username}`;
  if (codeInput) {
    codeInput.value = '';
    codeInput.focus();
  }
}

async function submitMfaChallenge() {
  const codeInput = document.getElementById('mfa-challenge-code');
  const btnSubmit = document.getElementById('btn-submit-mfa');
  const overlay = document.getElementById('login-overlay');
  const dock = document.getElementById('os-dock-container');

  if (!codeInput || !_pendingMfaToken) return;
  const rawCode = codeInput.value.trim();
  if (!rawCode) return;

  const isRecovery = codeInput.placeholder.includes('Recovery');
  const payload = {
    mfa_token: _pendingMfaToken,
    code: isRecovery ? undefined : rawCode,
    recovery_code: isRecovery ? rawCode : undefined
  };

  if (btnSubmit) {
    btnSubmit.disabled = true;
    btnSubmit.textContent = 'VERIFYING...';
  }

  try {
    const res = await window.fetch('/api/auth/mfa/challenge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      if (data.token) auth.setToken(data.token);
      if (data.user) setCurrentUser(data.user);

      document.documentElement.classList.remove('auth-required');
      document.documentElement.classList.add('has-auth-session');
      if (dock) dock.style.display = '';

      if (overlay) {
        overlay.style.transition = 'opacity 0.25s ease';
        overlay.style.opacity = '0';
        setTimeout(() => {
          overlay.style.display = 'none';
          overlay.style.opacity = '1';
        }, 250);
      }

      _pendingMfaToken = null;
      codeInput.value = '';
      ZettEventBus.emit('auth:login');
    } else {
      alert(`2FA Verification Failed: ${data.detail || 'Invalid code'}`);
      codeInput.value = '';
      codeInput.focus();
    }
  } catch (err) {
    alert(`Verification error: ${err.message}`);
  } finally {
    if (btnSubmit) {
      btnSubmit.disabled = false;
      btnSubmit.textContent = 'VERIFY & SIGN IN';
    }
  }
}

// ==============================================================================
// Inactivity Auto-Lock & Manual Lock Screen Overlay
// ==============================================================================

export function initLockOverlay() {
  const lockOverlay = document.getElementById('lock-overlay');
  const unlockBtn = document.getElementById('lock-unlock-btn');
  const unlockPwd = document.getElementById('lock-password');
  const switchBtn = document.getElementById('lock-switch-btn');

  if (unlockBtn) unlockBtn.addEventListener('click', unlockDesktop);
  if (unlockPwd) {
    unlockPwd.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') unlockDesktop();
    });
  }
  if (switchBtn) {
    switchBtn.addEventListener('click', switchUser);
  }

  // Global hotkey: Cmd+L or Ctrl+L to lock screen
  window.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'l') {
      e.preventDefault();
      lockDesktop();
    }
  });
}

export function lockDesktop() {
  const lockOverlay = document.getElementById('lock-overlay');
  if (!lockOverlay) return;

  _isLocked = true;
  sessionStorage.setItem('zettnas_desktop_locked', 'true');
  document.documentElement.classList.add('is-desktop-locked');
  document.body.classList.add('desktop-locked');
  lockOverlay.style.display = 'flex';
  lockOverlay.style.opacity = '1';

  try {
    if (!history.state || !history.state.zettnas_locked) {
      history.pushState({ zettnas_locked: true }, '', window.location.href);
    }
  } catch (e) {}

  updateLockClock();
  clearInterval(_clockInterval);
  _clockInterval = setInterval(updateLockClock, 1000);

  const pwdInput = document.getElementById('lock-password');
  const errorEl = document.getElementById('lock-error');
  if (errorEl) errorEl.style.display = 'none';
  if (pwdInput) {
    pwdInput.value = '';
    setTimeout(() => pwdInput.focus(), 100);
  }

  ZettEventBus.emit('auth:locked');
}

export async function unlockDesktop() {
  const pwdInput = document.getElementById('lock-password');
  const errorEl = document.getElementById('lock-error');
  const lockOverlay = document.getElementById('lock-overlay');
  const unlockBtn = document.getElementById('lock-unlock-btn');

  if (!pwdInput) return;
  const password = pwdInput.value;
  if (!password) return;

  const user = getCurrentUser();
  const username = user?.username || 'admin';

  if (unlockBtn) unlockBtn.disabled = true;

  try {
    const res = await window.fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, remember_me: true }),
      credentials: 'include'
    });

    const data = await res.json();
    if (res.ok && (data.status === 'ok' || data.token)) {
      if (data.token) auth.setToken(data.token);
      _isLocked = false;
      sessionStorage.removeItem('zettnas_desktop_locked');
      document.documentElement.classList.remove('is-desktop-locked');
      document.body.classList.remove('desktop-locked');
      clearInterval(_clockInterval);

      if (lockOverlay) {
        lockOverlay.style.transition = 'opacity 0.25s ease';
        lockOverlay.style.opacity = '0';
        setTimeout(() => {
          lockOverlay.style.display = 'none';
          lockOverlay.style.opacity = '1';
        }, 250);
      }

      pwdInput.value = '';
      resetInactivityTimer();
      ZettEventBus.emit('auth:unlocked');
    } else {
      if (errorEl) {
        errorEl.textContent = 'Incorrect password';
        errorEl.style.display = 'block';
      }
      pwdInput.select();
    }
  } catch (err) {
    if (errorEl) {
      errorEl.textContent = 'Connection error';
      errorEl.style.display = 'block';
    }
  } finally {
    if (unlockBtn) unlockBtn.disabled = false;
  }
}

function updateLockClock() {
  const clockEl = document.getElementById('lock-clock');
  const dateEl = document.getElementById('lock-date');
  const now = new Date();
  if (clockEl) {
    clockEl.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  if (dateEl) {
    dateEl.textContent = now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });
  }
}

export function switchUser() {
  const lockOverlay = document.getElementById('lock-overlay');
  if (lockOverlay) lockOverlay.style.display = 'none';
  clearInterval(_clockInterval);
  _isLocked = false;
  sessionStorage.removeItem('zettnas_desktop_locked');
  document.documentElement.classList.remove('is-desktop-locked');
  document.body.classList.remove('desktop-locked');

  // Trigger full login overlay in chooser mode
  _selectedUser = null;
  document.documentElement.classList.remove('has-auth-session');
  document.documentElement.classList.add('auth-required');

  const overlay = document.getElementById('login-overlay');
  const dock = document.getElementById('os-dock-container');
  if (overlay) {
    overlay.style.removeProperty('opacity');
    overlay.style.display = 'flex';
    renderLoginChooser({ forceChooser: true });
  }
  if (dock) dock.style.display = 'none';
}

export async function logout() {
  sessionStorage.removeItem('zettnas_desktop_locked');
  document.documentElement.classList.remove('is-desktop-locked');
  document.body.classList.remove('desktop-locked');
  _isLocked = false;
  _selectedUser = null;

  try {
    await window.fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
  } catch {}
  auth.clearToken();
  setCurrentUser(null);

  const credsStep = document.getElementById('login-step-credentials');
  const mfaStep = document.getElementById('login-step-mfa');
  if (credsStep) credsStep.style.display = 'block';
  if (mfaStep) mfaStep.style.display = 'none';

  const loginPwd = document.getElementById('login-password');
  if (loginPwd) loginPwd.value = '';

  document.documentElement.classList.remove('has-auth-session');
  document.documentElement.classList.add('auth-required');

  const overlay = document.getElementById('login-overlay');
  const dock = document.getElementById('os-dock-container');
  if (overlay) {
    overlay.style.removeProperty('opacity');
    overlay.style.display = 'flex';
    renderLoginChooser({ forceChooser: true });
  }
  if (dock) dock.style.display = 'none';

  ZettEventBus.emit('auth:logout');
  ZettEventBus.emit('auth:required');
}

// Inactivity Idle Tracker
function initInactivityTracker() {
  const events = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll'];
  events.forEach((evt) => {
    window.addEventListener(evt, resetInactivityTimer, { passive: true });
  });
  resetInactivityTimer();
}

function resetInactivityTimer() {
  if (_isLocked) return;
  clearTimeout(_autoLockTimer);

  const timeoutMs = parseInt(localStorage.getItem('zettnas_auto_lock_timeout_ms') || `${DEFAULT_IDLE_TIMEOUT_MS}`, 10);
  if (timeoutMs > 0) {
    _autoLockTimer = setTimeout(() => {
      // Don't auto-lock if login screen is currently active
      if (!document.documentElement.classList.contains('auth-required')) {
        lockDesktop();
      }
    }, timeoutMs);
  }
}
