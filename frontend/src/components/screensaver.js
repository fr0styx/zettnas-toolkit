/**
 * ZettNAS Toolkit - Consumer-Grade Screensaver & OLED Protection Engine
 * Provides animated screensavers (Matrix Digital Rain, Retro Nixie Clock, Hyperspace Starfield),
 * idle inactivity timers, OLED burn-in drift protection, and wake-to-lock capabilities.
 */
import { showToast } from '../toast.js';

let _screensaverInitialized = false;
let _screensaverControlsBound = false;
let _isActive = false;
let _isPreview = false;
let _animFrameId = null;
let _clockInterval = null;
let _driftInterval = null;
let _lastActivityTime = Date.now();
let _idleCheckInterval = null;

// Configuration
let _enabled = true;
let _timeoutMinutes = 10;
let _mode = 'matrix_rain'; // 'matrix_rain' | 'retro_clock' | 'starfield'
let _requireLock = false;

export function getScreensaverSettings() {
  return {
    enabled: _enabled,
    timeoutMinutes: _timeoutMinutes,
    mode: _mode,
    requireLock: _requireLock,
    isActive: _isActive
  };
}

export function applyScreensaverSettings(enabled, timeoutMinutes, mode, requireLock, persist = true) {
  _enabled = enabled !== undefined ? !!enabled : _enabled;
  _timeoutMinutes = timeoutMinutes !== undefined ? parseInt(timeoutMinutes, 10) : _timeoutMinutes;
  if (mode) _mode = mode;
  _requireLock = requireLock !== undefined ? !!requireLock : _requireLock;

  if (persist) {
    try {
      localStorage.setItem('zettnas_screensaver_enabled', String(_enabled));
      localStorage.setItem('zettnas_screensaver_timeout', String(_timeoutMinutes));
      localStorage.setItem('zettnas_screensaver_mode', _mode);
      localStorage.setItem('zettnas_screensaver_require_lock', String(_requireLock));
    } catch (e) {}
  }
}

export function initScreensaverSystem() {
  if (_screensaverInitialized) return;
  _screensaverInitialized = true;

  // Load persisted configuration
  try {
    const sEnabled = localStorage.getItem('zettnas_screensaver_enabled');
    if (sEnabled !== null) _enabled = sEnabled === 'true';

    const sTimeout = localStorage.getItem('zettnas_screensaver_timeout');
    if (sTimeout !== null) {
      const parsed = parseInt(sTimeout, 10);
      if (!isNaN(parsed) && parsed >= 0) _timeoutMinutes = parsed;
    }

    const sMode = localStorage.getItem('zettnas_screensaver_mode');
    if (sMode && ['matrix_rain', 'retro_clock', 'starfield'].includes(sMode)) {
      _mode = sMode;
    }

    const sLock = localStorage.getItem('zettnas_screensaver_require_lock');
    if (sLock !== null) _requireLock = sLock === 'true';
  } catch (e) {}

  // Idle Activity listeners
  const recordActivity = () => {
    _lastActivityTime = Date.now();
    if (_isActive) {
      deactivateScreensaver();
    }
  };

  window.addEventListener('pointermove', recordActivity, { passive: true });
  window.addEventListener('pointerdown', recordActivity, { passive: true });
  window.addEventListener('keydown', recordActivity, { passive: true });
  window.addEventListener('touchstart', recordActivity, { passive: true });
  window.addEventListener('wheel', recordActivity, { passive: true });

  // Heartbeat idle check every 3 seconds
  _idleCheckInterval = setInterval(() => {
    if (!_enabled || _timeoutMinutes <= 0 || _isActive) return;

    // Do not engage screensaver if desktop is already locked or initial setup overlay is open
    if (document.documentElement.classList.contains('is-desktop-locked') ||
        document.documentElement.classList.contains('auth-required')) {
      return;
    }

    const idleMs = Date.now() - _lastActivityTime;
    const thresholdMs = _timeoutMinutes * 60 * 1000;
    if (idleMs >= thresholdMs) {
      activateScreensaver(false);
    }
  }, 3000);

  // Initialize UI controls if present
  initScreensaverSettingsControls();
}

export function activateScreensaver(isPreview = false) {
  const container = document.getElementById('desktop-screensaver');
  if (!container) return;

  _isActive = true;
  _isPreview = isPreview;

  container.style.display = 'block';
  // Force reflow for CSS opacity transition
  void container.offsetWidth;
  container.classList.add('active');
  container.setAttribute('aria-hidden', 'false');

  const canvas = document.getElementById('screensaver-canvas');
  const clockEl = document.getElementById('screensaver-clock-display');

  if (_mode === 'retro_clock') {
    if (canvas) canvas.style.display = 'none';
    if (clockEl) {
      clockEl.style.display = 'block';
      startRetroClock(clockEl);
    }
  } else {
    if (clockEl) clockEl.style.display = 'none';
    if (canvas) {
      canvas.style.display = 'block';
      if (_mode === 'matrix_rain') {
        startMatrixRain(canvas);
      } else if (_mode === 'starfield') {
        startStarfield(canvas);
      }
    }
  }
}

export function deactivateScreensaver() {
  if (!_isActive) return;
  _isActive = false;

  const container = document.getElementById('desktop-screensaver');
  if (container) {
    container.classList.remove('active');
    setTimeout(() => {
      if (!_isActive) {
        container.style.display = 'none';
        container.setAttribute('aria-hidden', 'true');
      }
    }, 400);
  }

  // Stop animations and timers
  if (_animFrameId) {
    cancelAnimationFrame(_animFrameId);
    _animFrameId = null;
  }
  if (_clockInterval) {
    clearInterval(_clockInterval);
    _clockInterval = null;
  }
  if (_driftInterval) {
    clearInterval(_driftInterval);
    _driftInterval = null;
  }

  // Handle requireLock security option
  if (_requireLock && !_isPreview) {
    if (typeof window.lockDesktopScreen === 'function') {
      window.lockDesktopScreen();
    } else {
      document.documentElement.classList.add('is-desktop-locked');
    }
  }
}

// -------------------------------------------------------------
// 1. Matrix Digital Rain Animation Engine
// -------------------------------------------------------------
function startMatrixRain(canvas) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const w = (canvas.width = window.innerWidth);
  const h = (canvas.height = window.innerHeight);

  const fontSize = 16;
  const columns = Math.floor(w / fontSize);
  const drops = new Array(columns).fill(1);

  // Digital characters (katakana + numbers + latin symbols)
  const chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%&*+-/<>~ｦｱｳｴｵｶｷｹｺｻｼｽｾｿﾀﾂﾃﾅﾆﾇﾈﾊﾋﾎﾏﾐﾑﾒﾓﾔﾕﾗﾘﾜ';

  ctx.fillStyle = '#000000';
  ctx.fillRect(0, 0, w, h);

  let lastFrame = Date.now();
  const fps = 30;
  const frameInterval = 1000 / fps;

  function draw() {
    if (!_isActive) return;
    _animFrameId = requestAnimationFrame(draw);

    const now = Date.now();
    const elapsed = now - lastFrame;
    if (elapsed < frameInterval) return;
    lastFrame = now - (elapsed % frameInterval);

    // Translucent black overlay creating trailing fading phosphor effect
    ctx.fillStyle = 'rgba(0, 0, 0, 0.07)';
    ctx.fillRect(0, 0, w, h);

    ctx.font = `${fontSize}px monospace`;

    for (let i = 0; i < drops.length; i++) {
      const char = chars[Math.floor(Math.random() * chars.length)];
      const x = i * fontSize;
      const y = drops[i] * fontSize;

      // Leading character bright highlight
      ctx.fillStyle = '#bbf7d0';
      ctx.fillText(char, x, y);

      // Trailing characters neon green
      ctx.fillStyle = '#22c55e';
      ctx.fillText(char, x, y - fontSize);

      if (y > h && Math.random() > 0.975) {
        drops[i] = 0;
      }
      drops[i]++;
    }
  }

  draw();
}

// -------------------------------------------------------------
// 2. Retro Nixie / Digital Clock Engine with OLED Anti-Burn-In Drift
// -------------------------------------------------------------
function startRetroClock(clockEl) {
  const timeEl = document.getElementById('screensaver-time');
  const dateEl = document.getElementById('screensaver-date');

  const update = () => {
    const d = new Date();
    if (timeEl) {
      timeEl.textContent = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    }
    if (dateEl) {
      dateEl.textContent = d.toLocaleDateString([], { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
    }
  };

  update();
  _clockInterval = setInterval(update, 1000);

  // Gentle position drift every 45 seconds to prevent pixel phosphor burn-in on OLED displays
  const driftPositions = [
    { top: '35%', left: '48%' },
    { top: '45%', left: '52%' },
    { top: '42%', left: '46%' },
    { top: '38%', left: '54%' },
    { top: '40%', left: '50%' }
  ];
  let driftIdx = 0;

  _driftInterval = setInterval(() => {
    driftIdx = (driftIdx + 1) % driftPositions.length;
    const target = driftPositions[driftIdx];
    clockEl.style.top = target.top;
    clockEl.style.left = target.left;
  }, 45000);
}

// -------------------------------------------------------------
// 3. Hyperspace Starfield Animation Engine
// -------------------------------------------------------------
function startStarfield(canvas) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const w = (canvas.width = window.innerWidth);
  const h = (canvas.height = window.innerHeight);

  const numStars = 450;
  const stars = [];

  for (let i = 0; i < numStars; i++) {
    stars.push({
      x: (Math.random() - 0.5) * w * 2,
      y: (Math.random() - 0.5) * h * 2,
      z: Math.random() * w
    });
  }

  const cx = w / 2;
  const cy = h / 2;

  function draw() {
    if (!_isActive) return;
    _animFrameId = requestAnimationFrame(draw);

    ctx.fillStyle = 'rgba(0, 0, 0, 0.25)';
    ctx.fillRect(0, 0, w, h);

    for (let i = 0; i < numStars; i++) {
      const s = stars[i];
      s.z -= 8; // Star velocity
      if (s.z <= 0) {
        s.x = (Math.random() - 0.5) * w * 2;
        s.y = (Math.random() - 0.5) * h * 2;
        s.z = w;
      }

      const k = 250 / s.z;
      const px = s.x * k + cx;
      const py = s.y * k + cy;

      if (px >= 0 && px <= w && py >= 0 && py <= h) {
        const size = Math.max(0.5, (1 - s.z / w) * 3);
        const alpha = Math.min(1, (1 - s.z / w) * 1.2);
        ctx.fillStyle = `rgba(224, 242, 254, ${alpha})`;
        ctx.beginPath();
        ctx.arc(px, py, size, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  draw();
}

// -------------------------------------------------------------
// 4. Mission Control Settings UI Binding
// -------------------------------------------------------------
export function initScreensaverSettingsControls() {
  if (_screensaverControlsBound) return;

  const enableToggle = document.getElementById('screensaver-enable-toggle');
  const timeoutSelect = document.getElementById('screensaver-timeout-select');
  const lockToggle = document.getElementById('screensaver-lock-toggle');
  const previewBtn = document.getElementById('screensaver-preview-btn');
  const resetBtn = document.getElementById('screensaver-reset-btn');
  const styleCards = document.querySelectorAll('.screensaver-style-card');

  if (!enableToggle && !previewBtn && !styleCards.length) return;
  _screensaverControlsBound = true;

  // Sync state to UI elements
  if (enableToggle) {
    enableToggle.checked = _enabled;
    enableToggle.addEventListener('change', (e) => {
      applyScreensaverSettings(e.target.checked, undefined, undefined, undefined, true);
    });
  }

  if (timeoutSelect) {
    timeoutSelect.value = String(_timeoutMinutes);
    timeoutSelect.addEventListener('change', (e) => {
      applyScreensaverSettings(undefined, e.target.value, undefined, undefined, true);
    });
  }

  if (lockToggle) {
    lockToggle.checked = _requireLock;
    lockToggle.addEventListener('change', (e) => {
      applyScreensaverSettings(undefined, undefined, undefined, e.target.checked, true);
    });
  }

  // Style cards selection
  styleCards.forEach((card) => {
    const cardMode = card.getAttribute('data-mode');
    if (cardMode === _mode) {
      card.classList.add('active');
      card.setAttribute('aria-checked', 'true');
    } else {
      card.classList.remove('active');
      card.setAttribute('aria-checked', 'false');
    }

    card.addEventListener('click', () => {
      styleCards.forEach((c) => {
        c.classList.remove('active');
        c.setAttribute('aria-checked', 'false');
      });
      card.classList.add('active');
      card.setAttribute('aria-checked', 'true');
      applyScreensaverSettings(undefined, undefined, cardMode, undefined, true);
    });
  });

  if (previewBtn) {
    previewBtn.addEventListener('click', () => {
      activateScreensaver(true);
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      applyScreensaverSettings(true, 10, 'matrix_rain', false, true);
      if (enableToggle) enableToggle.checked = true;
      if (timeoutSelect) timeoutSelect.value = '10';
      if (lockToggle) lockToggle.checked = false;
      styleCards.forEach((c) => {
        const isMatrix = c.getAttribute('data-mode') === 'matrix_rain';
        c.classList.toggle('active', isMatrix);
        c.setAttribute('aria-checked', isMatrix ? 'true' : 'false');
      });
      showToast('Screensaver settings restored to defaults', 'success');
    });
  }
}

// Expose globals for window testing & cross-module integration
if (typeof window !== 'undefined') {
  window.initScreensaverSystem = initScreensaverSystem;
  window.activateScreensaver = activateScreensaver;
  window.deactivateScreensaver = deactivateScreensaver;
  window.getScreensaverSettings = getScreensaverSettings;
  window.applyScreensaverSettings = applyScreensaverSettings;
  window.initScreensaverSettingsControls = initScreensaverSettingsControls;
}
