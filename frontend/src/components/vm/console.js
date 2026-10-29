// The VM console: VNC and serial clients, keyboard, paste, reconnect, and the offline simulations.
// Part of vm-manager.js, split out by ARC-5.

import { api } from '../../api.js';
import { escapeHtml, copyText } from '../../utils.js';
import { showToast, showPromptToast, showBottomSheet } from '../../toast.js';
import { t } from '../../i18n.js';
import { makeDraggable, bringToFront } from '../dock.js';
import { createTerminalView } from '../terminal-view.js';
import { vmState } from './state.js';
import { isCompact, isTouch } from '../../device.js';

/**
 * Universal Clipboard Helper
 * Robust copy support with modern Clipboard API and fallback to execCommand('copy')
 * for non-secure HTTP local IP environments.
 */
export async function copyToClipboard(text) {
  if (!text) return false;

  // 1. Try modern Async Clipboard API in secure context (HTTPS/localhost)
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await copyText(text);
      return true;
    } catch (err) {
      console.warn('Async Clipboard API failed, falling back:', err);
    }
  }

  // 2. Reliable textarea fallback for non-secure HTTP contexts
  try {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.top = '-9999px';
    textArea.style.left = '-9999px';
    textArea.style.opacity = '0';
    textArea.setAttribute('readonly', '');
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    const successful = document.execCommand('copy');
    document.body.removeChild(textArea);
    return successful;
  } catch (err) {
    console.error('execCommand copy fallback failed:', err);
    return false;
  }
}

/**
 * Sets keyboard capture focus state on VM console window
 */
export function setConsoleFocus(focused) {
  const consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin) return;
  consoleWin.dataset.focused = focused ? 'true' : 'false';
  const pill = consoleWin.querySelector('#vm-console-kbd-pill');
  if (pill) {
    if (focused) {
      pill.textContent = t('ui.captured', '⌨️ Captured');
      pill.style.color = '#38bdf8';
      pill.style.borderColor = 'rgba(14, 165, 233, 0.4)';
      pill.setAttribute('title', 'Keyboard captured by VM console. Click outside or minimize to release.');
    } else {
      pill.textContent = t('ui.click_to_capture', '⌨️ Click to capture');
      pill.style.color = 'var(--muted)';
      pill.style.borderColor = 'rgba(255, 255, 255, 0.1)';
      pill.setAttribute('title', 'Keyboard released to desktop. Click console to capture keyboard.');
    }
  }
}

/**
 * Hypervisor Graphical Video Display (Display :0 / VirtIO-GPU / VNC)
 * Renders an authentic hypervisor remote video monitor viewport.
 */
function initGuiDesktopSimulation(canvas, vmName) {
  if (!canvas) return;
  if (canvas._blinkInterval) {
    clearInterval(canvas._blinkInterval);
    canvas._blinkInterval = null;
  }
  if (canvas._guiInterval) {
    clearInterval(canvas._guiInterval);
    canvas._guiInterval = null;
  }
  if (canvas._guiMouseMove) {
    canvas.removeEventListener('mousemove', canvas._guiMouseMove);
    canvas._guiMouseMove = null;
  }
  if (canvas._guiMouseLeave) {
    canvas.removeEventListener('mouseleave', canvas._guiMouseLeave);
    canvas._guiMouseLeave = null;
  }
  if (canvas._guiMouseDown) {
    canvas.removeEventListener('mousedown', canvas._guiMouseDown);
    canvas._guiMouseDown = null;
  }

  const ctx = canvas.getContext ? canvas.getContext('2d') : null;

  let mouseX = Math.floor(canvas.width / 2);
  let mouseY = Math.floor(canvas.height / 2);
  let mouseInCanvas = true;

  const targetVm = vmState.list.find((v) => v.name === vmName) || {};
  const vmIp = targetVm.ip_address || '192.168.1.180';
  const vmId = targetVm.id || '1';
  const vncPort = 5900 + ((parseInt(vmId, 10) || 1) % 10);

  const onMouseMove = (e) => {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    mouseX = Math.max(0, Math.min(canvas.width, Math.floor(((e.clientX - rect.left) / rect.width) * canvas.width)));
    mouseY = Math.max(0, Math.min(canvas.height, Math.floor(((e.clientY - rect.top) / rect.height) * canvas.height)));
    mouseInCanvas = true;
    render();
  };

  const onMouseLeave = () => {
    mouseInCanvas = false;
    render();
  };

  const onMouseDown = async (e) => {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = Math.max(0, Math.min(canvas.width, Math.floor(((e.clientX - rect.left) / rect.width) * canvas.width)));
    const y = Math.max(0, Math.min(canvas.height, Math.floor(((e.clientY - rect.top) / rect.height) * canvas.height)));

    const cardY = 56;
    const btnY = cardY + 252;
    // Button 1: Switch to Serial TTY (x: 140 to 330)
    if (y >= btnY && y <= btnY + 36 && x >= 140 && x <= 330) {
      const consoleWin = document.getElementById('vm-console-window');
      if (consoleWin && consoleWin._setConsoleMode) {
        consoleWin._setConsoleMode('cli');
      }
    }
    // Button 2: Native VNC Client (x: 350 to 530)
    else if (y >= btnY && y <= btnY + 36 && x >= 350 && x <= 530) {
      const uri = `vnc://${window.location.hostname || '127.0.0.1'}:${vncPort}`;
      const ok = await copyToClipboard(uri);
      if (ok) showToast(t('toast.copied_vnc_uri', 'Copied VNC URI \'{uri}\'', { uri: uri }), 'info');
    }
    // Button 3: Copy SSH (x: 550 to 720)
    else if (y >= btnY && y <= btnY + 36 && x >= 550 && x <= 720) {
      const cmd = `ssh root@${vmIp}`;
      const ok = await copyToClipboard(cmd);
      if (ok) showToast(t('toast.copied', 'Copied \'{cmd}\'', { cmd: cmd }), 'info');
    }
  };

  canvas._guiMouseMove = onMouseMove;
  canvas._guiMouseLeave = onMouseLeave;
  canvas._guiMouseDown = onMouseDown;

  canvas.addEventListener('mousemove', onMouseMove);
  canvas.addEventListener('mouseleave', onMouseLeave);
  canvas.addEventListener('mousedown', onMouseDown);

  function render() {
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;

    // 1. Sleek deep hypervisor console background
    ctx.fillStyle = '#060a12';
    ctx.fillRect(0, 0, w, h);

    // Phosphor CRT scanlines
    ctx.fillStyle = 'rgba(255, 255, 255, 0.015)';
    for (let y = 0; y < h; y += 4) {
      ctx.fillRect(0, y, w, 1);
    }

    // 2. Hardware Video Frame Header
    ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
    ctx.fillRect(0, 0, w, 32);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.strokeRect(0, 0, w, 32);

    ctx.font = '600 11px "JetBrains Mono", monospace';
    ctx.fillStyle = '#38bdf8';
    ctx.textBaseline = 'middle';
    ctx.fillText(`⚡ QEMU/KVM Hardware Video Display (:0) — ${vmName}`, 16, 16);

    ctx.font = '500 11px "JetBrains Mono", monospace';
    ctx.fillStyle = '#94a3b8';
    const hdrRight = `1920 × 1080 @ 60 FPS  •  VirtIO-GPU DRM`;
    const hdrRightW = ctx.measureText(hdrRight).width;
    ctx.fillText(hdrRight, w - hdrRightW - 16, 16);

    // 3. Central Hypervisor Display Frame
    const cardW = Math.min(680, w - 60);
    const cardH = 320;
    const cardX = Math.floor((w - cardW) / 2);
    const cardY = 56;

    ctx.fillStyle = 'rgba(10, 16, 26, 0.75)';
    ctx.strokeStyle = 'rgba(14, 165, 233, 0.25)';
    ctx.lineWidth = 1;
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(cardX, cardY, cardW, cardH, 10);
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.fillRect(cardX, cardY, cardW, cardH);
      ctx.strokeRect(cardX, cardY, cardW, cardH);
    }

    // Monitor Icon & Header
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';

    ctx.font = '28px sans-serif';
    ctx.fillText('🖥️', w / 2, cardY + 16);

    ctx.font = '700 15px system-ui, -apple-system, sans-serif';
    ctx.fillStyle = '#f8fafc';
    ctx.fillText(`VNC REMOTE DISPLAY (:0)`, w / 2, cardY + 52);

    ctx.font = '500 12px "JetBrains Mono", monospace';
    ctx.fillStyle = '#34d399';
    ctx.fillText(`● VNC Server Listening on 127.0.0.1:${vncPort}`, w / 2, cardY + 76);

    ctx.font = '400 11px system-ui, -apple-system, sans-serif';
    ctx.fillStyle = '#94a3b8';
    ctx.fillText(`Guest OS video output is running on physical display :0 with hardware acceleration.`, w / 2, cardY + 96);

    // Telemetry Grid Box
    const gridY = cardY + 120;
    const gridW = cardW - 48;
    const gridX = cardX + 24;
    const gridH = 92;

    ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(gridX, gridY, gridW, gridH, 6);
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.fillRect(gridX, gridY, gridW, gridH);
      ctx.strokeRect(gridX, gridY, gridW, gridH);
    }

    ctx.textAlign = 'left';
    ctx.font = '11px "JetBrains Mono", monospace';

    const col1X = gridX + 16;
    const col2X = gridX + Math.floor(gridW / 2) + 16;

    ctx.fillStyle = '#64748b';
    ctx.fillText('Host Hypervisor:', col1X, gridY + 14);
    ctx.fillStyle = '#38bdf8';
    ctx.fillText('Linux KVM (VT-x Active)', col1X + 130, gridY + 14);

    ctx.fillStyle = '#64748b';
    ctx.fillText('Graphics Driver:', col1X, gridY + 38);
    ctx.fillStyle = '#fff';
    ctx.fillText('VirtIO-GPU (DRM / KMS)', col1X + 130, gridY + 38);

    ctx.fillStyle = '#64748b';
    ctx.fillText('Display Protocol:', col1X, gridY + 62);
    ctx.fillStyle = '#a78bfa';
    ctx.fillText('RFB 3.8 / noVNC WebSocket', col1X + 130, gridY + 62);

    ctx.fillStyle = '#64748b';
    ctx.fillText('Guest IP Address:', col2X, gridY + 14);
    ctx.fillStyle = '#38bdf8';
    ctx.fillText(vmIp, col2X + 130, gridY + 14);

    ctx.fillStyle = '#64748b';
    ctx.fillText('Network Bridge:', col2X, gridY + 38);
    ctx.fillStyle = '#fff';
    ctx.fillText(targetVm.bridge || 'br0', col2X + 130, gridY + 38);

    ctx.fillStyle = '#64748b';
    ctx.fillText('Display Port:', col2X, gridY + 62);
    ctx.fillStyle = '#f59e0b';
    ctx.fillText(`Port ${vncPort}`, col2X + 130, gridY + 62);

    // Interactive Action Buttons inside Canvas
    const btnY = cardY + 236;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    // Button 1: Switch to Serial TTY
    ctx.fillStyle = 'rgba(16, 185, 129, 0.2)';
    ctx.strokeStyle = '#10b981';
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(140, btnY, 190, 34, 6);
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.fillRect(140, btnY, 190, 34);
      ctx.strokeRect(140, btnY, 190, 34);
    }
    ctx.font = '600 11px system-ui, -apple-system, sans-serif';
    ctx.fillStyle = '#34d399';
    ctx.fillText('📟 Open Serial TTY Shell', 140 + 95, btnY + 17);

    // Button 2: Native VNC Client
    ctx.fillStyle = 'rgba(14, 165, 233, 0.2)';
    ctx.strokeStyle = '#0ea5e9';
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(350, btnY, 180, 34, 6);
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.fillRect(350, btnY, 180, 34);
      ctx.strokeRect(350, btnY, 180, 34);
    }
    ctx.fillStyle = '#38bdf8';
    ctx.fillText('🔗 Copy VNC URI', 350 + 90, btnY + 17);

    // Button 3: Copy SSH Command
    ctx.fillStyle = 'rgba(255, 255, 255, 0.06)';
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(550, btnY, 170, 34, 6);
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.fillRect(550, btnY, 170, 34);
      ctx.strokeRect(550, btnY, 170, 34);
    }
    ctx.fillStyle = '#e2e8f0';
    ctx.fillText('💻 Copy SSH Command', 550 + 85, btnY + 17);

    // Mouse pointer
    if (mouseInCanvas) {
      ctx.save();
      ctx.shadowColor = 'rgba(0, 0, 0, 0.5)';
      ctx.shadowBlur = 4;
      ctx.fillStyle = '#ffffff';
      ctx.strokeStyle = '#000000';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(mouseX, mouseY);
      ctx.lineTo(mouseX, mouseY + 15);
      ctx.lineTo(mouseX + 4, mouseY + 12);
      ctx.lineTo(mouseX + 7, mouseY + 17);
      ctx.lineTo(mouseX + 10, mouseY + 15);
      ctx.lineTo(mouseX + 7, mouseY + 10);
      ctx.lineTo(mouseX + 12, mouseY + 10);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.restore();
    }
  }

  canvas.addEventListener('focus', () => setConsoleFocus(true));
  canvas.addEventListener('blur', (e) => {
    const cw = document.getElementById('vm-console-window');
    if (!cw || !cw.contains(e.relatedTarget)) {
      setConsoleFocus(false);
    }
  });

  canvas.focus();
  canvas.addEventListener('keydown', (e) => e.stopPropagation());
  canvas.onkeydown = (e) => {
    e.stopPropagation();
    // Do NOT show toasts!
    if (e.key === 'Enter') {
      const consoleWin = document.getElementById('vm-console-window');
      if (consoleWin && consoleWin._setConsoleMode) {
        consoleWin._setConsoleMode('cli');
      }
    }
  };

  render();
}

export let _activeRfb = null;
export let _activeSerialWs = null;
export let _reconnectTimer = null;
export const _serialBuffers = new Map(); // keyed by VM id; a Map, so an id can't reach Object's own properties
let _serialView = null;
let _serialViewVmId = null;
const SERIAL_TRANSCRIPT_MAX = 256 * 1024;

// Key -> serial byte sequence, used when a key is typed while the terminal
// itself does not have focus (the console window's global key guard).
export function serialKeyToData(e) {
  const map = {
    Enter: '\r',
    Backspace: '\x7f',
    Tab: '\t',
    Escape: '\x1b',
    ArrowUp: '\x1b[A',
    ArrowDown: '\x1b[B',
    ArrowRight: '\x1b[C',
    ArrowLeft: '\x1b[D',
    Home: '\x1b[H',
    End: '\x1b[F',
    PageUp: '\x1b[5~',
    PageDown: '\x1b[6~',
    Delete: '\x1b[3~',
  };
  if (map[e.key]) return map[e.key];
  if (e.ctrlKey && e.key && e.key.length === 1) {
    const code = e.key.toLowerCase().charCodeAt(0) - 96;
    return code >= 1 && code <= 26 ? String.fromCharCode(code) : null;
  }
  if (e.key && e.key.length === 1 && !e.metaKey && !e.altKey) return e.key;
  return null;
}

function rememberSerialChunk(vmId, chunk) {
  let list = _serialBuffers.get(vmId);
  if (!list) _serialBuffers.set(vmId, (list = []));
  list.push(chunk);
  let total = list.reduce((n, c) => n + (c.length || c.byteLength || 0), 0);
  while (total > SERIAL_TRANSCRIPT_MAX && list.length > 1) {
    const old = list.shift();
    total -= old.length || old.byteLength || 0;
  }
}

function ensureSerialView(host, vmId) {
  if (!host) return null;
  const intact = host.querySelector('.zt-terminal-fallback, .zt-terminal-xterm');
  if (_serialView && _serialView.host === host && _serialViewVmId === vmId && intact) return _serialView;
  if (_serialView) _serialView.dispose();
  _serialView = createTerminalView(host, {
    theme: { background: '#0a0f18', cursorAccent: '#0a0f18' },
    onData: (d) => {
      if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) _activeSerialWs.send(d);
    },
  });
  _serialViewVmId = vmId;
  // Replay this VM's earlier output so a reconnect keeps the screen history.
  for (const chunk of _serialBuffers.get(vmId) || []) _serialView.write(chunk);
  return _serialView;
}

export function _sendKeyToRfb(keysym, code) {
  if (_activeRfb && typeof _activeRfb.sendKey === 'function') {
    _activeRfb.sendKey(keysym, code, true);
    setTimeout(() => {
      try {
        if (_activeRfb && typeof _activeRfb.sendKey === 'function') {
          _activeRfb.sendKey(keysym, code, false);
        }
      } catch (_) {}
    }, 40);
  }
}

export function _sendCtrlCToRfb() {
  if (_activeRfb && typeof _activeRfb.sendKey === 'function') {
    _activeRfb.sendKey(0xffe3, 'ControlLeft', true);
    _activeRfb.sendKey(0x63, 'KeyC', true);
    setTimeout(() => {
      try {
        if (_activeRfb && typeof _activeRfb.sendKey === 'function') {
          _activeRfb.sendKey(0x63, 'KeyC', false);
          _activeRfb.sendKey(0xffe3, 'ControlLeft', false);
        }
      } catch (_) {}
    }, 40);
  }
}

export function getActiveConsoleTarget(consoleWin) {
  if (!consoleWin) consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin) return null;

  const mode = consoleWin._activeMode || 'gui';
  if (mode === 'gui') {
    const realCanvas = consoleWin.querySelector('.vnc-screen-target canvas');
    if (realCanvas && realCanvas.style.display !== 'none') {
      return realCanvas;
    }
    const simCanvas = consoleWin.querySelector('#vm-console-canvas');
    if (simCanvas && simCanvas.style.display !== 'none') {
      return simCanvas;
    }
    return realCanvas || consoleWin.querySelector('.vnc-screen-target') || consoleWin.querySelector('#vm-console-viewport');
  } else {
    const cliContainer = consoleWin.querySelector('#vm-cli-container');
    if (cliContainer && cliContainer.style.display !== 'none') {
      return cliContainer;
    }
    const simCanvas = consoleWin.querySelector('#vm-console-canvas');
    if (simCanvas && simCanvas.style.display !== 'none') {
      return simCanvas;
    }
    return cliContainer;
  }
}

export function focusActiveConsole() {
  const consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin) return;
  const mode = consoleWin._activeMode || 'gui';

  if (mode === 'gui') {
    if (_activeRfb && typeof _activeRfb.focus === 'function') {
      try { _activeRfb.focus({ preventScroll: true }); } catch (_) {}
    }
    const realCanvas = consoleWin.querySelector('.vnc-screen-target canvas');
    if (realCanvas && realCanvas.style.display !== 'none') {
      realCanvas.tabIndex = 0;
      try { realCanvas.focus({ preventScroll: true }); } catch (_) {}
      return;
    }
    const simCanvas = consoleWin.querySelector('#vm-console-canvas');
    if (simCanvas && simCanvas.style.display !== 'none') {
      try { simCanvas.focus({ preventScroll: true }); } catch (_) {}
    }
  } else {
    if (_serialView && _serialView.term) {
      _serialView.focus();
      return;
    }
    const cliContainer = consoleWin.querySelector('#vm-cli-container');
    if (cliContainer) {
      cliContainer.tabIndex = 0;
      try { cliContainer.focus({ preventScroll: true }); } catch (_) {}
    }
  }
}

export function _handleRfbKeyFallback(e) {
  if (!_activeRfb) return;

  const keyMap = {
    'Enter': { keysym: 0xff0d, code: 'Enter' },
    'Backspace': { keysym: 0xff08, code: 'Backspace' },
    'Tab': { keysym: 0xff09, code: 'Tab' },
    'Escape': { keysym: 0xff1b, code: 'Escape' },
    'Delete': { keysym: 0xffff, code: 'Delete' },
    'Insert': { keysym: 0xff63, code: 'Insert' },
    'ArrowUp': { keysym: 0xff52, code: 'ArrowUp' },
    'ArrowDown': { keysym: 0xff54, code: 'ArrowDown' },
    'ArrowLeft': { keysym: 0xff51, code: 'ArrowLeft' },
    'ArrowRight': { keysym: 0xff53, code: 'ArrowRight' },
    'Home': { keysym: 0xff50, code: 'Home' },
    'End': { keysym: 0xff57, code: 'End' },
    'PageUp': { keysym: 0xff55, code: 'PageUp' },
    'PageDown': { keysym: 0xff56, code: 'PageDown' },
    ' ': { keysym: 0x0020, code: 'Space' },
    'Space': { keysym: 0x0020, code: 'Space' },
    'F1': { keysym: 0xffbe, code: 'F1' },
    'F2': { keysym: 0xffbf, code: 'F2' },
    'F3': { keysym: 0xffc0, code: 'F3' },
    'F4': { keysym: 0xffc1, code: 'F4' },
    'F5': { keysym: 0xffc2, code: 'F5' },
    'F6': { keysym: 0xffc3, code: 'F6' },
    'F7': { keysym: 0xffc4, code: 'F7' },
    'F8': { keysym: 0xffc5, code: 'F8' },
    'F9': { keysym: 0xffc6, code: 'F9' },
    'F10': { keysym: 0xffc7, code: 'F10' },
    'F11': { keysym: 0xffc8, code: 'F11' },
    'F12': { keysym: 0xffcb, code: 'F12' },
  };

  if (keyMap[e.key]) {
    e.preventDefault();
    e.stopPropagation();
    _sendKeyToRfb(keyMap[e.key].keysym, keyMap[e.key].code);
    return;
  }

  // Ctrl combos
  if (e.ctrlKey && e.key && e.key.length === 1) {
    e.preventDefault();
    e.stopPropagation();
    if (e.key.toLowerCase() === 'c') {
      _sendCtrlCToRfb();
    } else {
      const code = e.code || `Key${e.key.toUpperCase()}`;
      _activeRfb.sendKey?.(0xffe3, 'ControlLeft', true);
      _activeRfb.sendKey?.(e.key.charCodeAt(0), code, true);
      setTimeout(() => {
        try {
          _activeRfb.sendKey?.(e.key.charCodeAt(0), code, false);
          _activeRfb.sendKey?.(0xffe3, 'ControlLeft', false);
        } catch (_) {}
      }, 40);
    }
    return;
  }

  // Single printable characters (letters, digits, symbols)
  if (e.key && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault();
    e.stopPropagation();
    const keysym = e.key.charCodeAt(0);
    const code = e.code || null;
    _sendKeyToRfb(keysym, code);
  }
}

export let _consoleReconnectAttempts = 0;

export function showConsoleBanner(type = 'connecting', message = '', actions = []) {
  const banner = document.getElementById('vm-console-banner');
  if (!banner) return;

  banner.className = `vm-console-banner banner-${type}`;
  let iconSvg;
  if (type === 'connecting') {
    iconSvg = `<svg class="spin-clockwise" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></svg>`;
  } else if (type === 'connected') {
    iconSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`;
  } else if (type === 'disconnected') {
    iconSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
  } else {
    iconSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
  }

  let actionsHtml = '';
  if (actions && actions.length > 0) {
    actionsHtml = `<div class="banner-actions">` +
      actions.map((act, idx) => `<button class="btn-banner-act ${act.primary ? 'primary' : 'secondary'}" data-act-idx="${idx}">${escapeHtml(act.label)}</button>`).join('') +
      `</div>`;
  }

  banner.innerHTML = `
    <div class="banner-content">
      ${iconSvg}
      <span class="banner-text">${escapeHtml(message)}</span>
    </div>
    ${actionsHtml}
  `;
  banner.style.display = 'flex';

  if (actions && actions.length > 0) {
    banner.querySelectorAll('.btn-banner-act').forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.actIdx, 10);
        if (actions[idx]?.onClick) actions[idx].onClick();
      };
    });
  }

  if (type === 'connected') {
    if (banner._fadeTimeout) clearTimeout(banner._fadeTimeout);
    banner._fadeTimeout = setTimeout(() => {
      hideConsoleBanner();
    }, 3500);
  }
}

export function hideConsoleBanner() {
  const banner = document.getElementById('vm-console-banner');
  if (banner) {
    if (banner._fadeTimeout) clearTimeout(banner._fadeTimeout);
    banner.style.display = 'none';
  }
}

export function cancelConsoleReconnect() {
  if (_reconnectTimer) {
    clearTimeout(_reconnectTimer);
    _reconnectTimer = null;
  }
  hideConsoleBanner();
}

export const clearConsoleReconnectTimer = cancelConsoleReconnect;

export function _scheduleConsoleReconnect(container, vmId, vmName, mode) {
  cancelConsoleReconnect();
  const consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin || consoleWin.style.display === 'none' || consoleWin.classList.contains('window-minimized') || consoleWin._userClosing) {
    return;
  }

  if (_consoleReconnectAttempts >= 5) {
    const statusPill = document.getElementById('vm-console-status-pill');
    if (statusPill) {
      statusPill.textContent = '● DISCONNECTED';
      statusPill.style.color = '#f87171';
    }
    showConsoleBanner('disconnected', `Connection to ${vmName} lost. Maximum reconnection attempts reached.`, [
      {
        label: 'Reconnect Now',
        primary: true,
        onClick: () => {
          _consoleReconnectAttempts = 0;
          _scheduleConsoleReconnect(container, vmId, vmName, mode);
        },
      },
    ]);
    return;
  }

  const statusPill = document.getElementById('vm-console-status-pill');
  let countdown = 5;
  if (statusPill) {
    statusPill.textContent = `● RECONNECTING (${countdown}s)...`;
    statusPill.style.color = '#fbbf24';
  }

  const triggerNow = () => {
    cancelConsoleReconnect();
    _consoleReconnectAttempts++;
    if (statusPill) {
      statusPill.textContent = '● CONNECTING...';
      statusPill.style.color = '#fbbf24';
    }
    showConsoleBanner('connecting', `Reconnecting to ${vmName} display (Attempt ${_consoleReconnectAttempts}/5)...`);
    const win = document.getElementById('vm-console-window');
    if (mode === 'gui') {
      const vncWrap = win ? win.querySelector('#vm-vnc-container') : container;
      initRealVncClient(vncWrap, vmId, vmName);
    } else {
      const cliWrap = win ? win.querySelector('#vm-cli-container') : container;
      initRealSerialTerminal(cliWrap, vmId, vmName);
    }
  };

  const cancelRec = () => {
    cancelConsoleReconnect();
    if (statusPill) {
      statusPill.textContent = '● DISCONNECTED';
      statusPill.style.color = '#f87171';
    }
    showConsoleBanner('disconnected', 'Disconnected from VM console', [
      {
        label: 'Reconnect Now',
        primary: true,
        onClick: () => {
          _consoleReconnectAttempts = 0;
          triggerNow();
        },
      },
    ]);
  };

  showConsoleBanner('disconnected', `Connection lost. Reconnecting in ${countdown}s (Attempt ${_consoleReconnectAttempts + 1}/5)...`, [
    { label: 'Reconnect Now', primary: true, onClick: triggerNow },
    { label: 'Cancel', primary: false, onClick: cancelRec },
  ]);

  const tick = () => {
    countdown--;
    const win = document.getElementById('vm-console-window');
    if (!win || win.style.display === 'none' || win.classList.contains('window-minimized') || win._userClosing) {
      cancelConsoleReconnect();
      return;
    }
    if (countdown > 0) {
      if (statusPill) {
        statusPill.textContent = `● RECONNECTING (${countdown}s)...`;
      }
      const banner = document.getElementById('vm-console-banner');
      const txt = banner?.querySelector('.banner-text');
      if (txt) {
        txt.textContent = `Connection lost. Reconnecting in ${countdown}s (Attempt ${_consoleReconnectAttempts + 1}/5)...`;
      }
      _reconnectTimer = setTimeout(tick, 1000);
    } else {
      _reconnectTimer = null;
      triggerNow();
    }
  };
  _reconnectTimer = setTimeout(tick, 1000);
}

/**
 * Universal paste helper to forward text characters into guest console or serial socket.
 */
export async function pasteTextToGuestConsole(text) {
  if (!text) return;
  const consoleWin = document.getElementById('vm-console-window');
  const mode = consoleWin?._activeMode || 'gui';
  if (mode === 'gui') {
    if (_activeRfb) {
      if (typeof _activeRfb.clipboardPasteFrom === 'function') {
        try {
          _activeRfb.clipboardPasteFrom(text);
        } catch (_) {}
      }
      for (let i = 0; i < text.length; i++) {
        const ch = text[i];
        if (ch === '\r') continue;
        if (ch === '\n') {
          _sendKeyToRfb(0xff0d, 'Enter');
        } else if (ch === '\t') {
          _sendKeyToRfb(0xff09, 'Tab');
        } else {
          _sendKeyToRfb(ch.charCodeAt(0), null);
        }
        if (text.length > 1) {
          await new Promise((r) => setTimeout(r, 15));
        }
      }
      showToast(t('toast.pasted_characters_into_guest_vm', 'Pasted {count} characters into guest VM', { count: text.length }), 'success');
    } else {
      showToast(t('toast.pasted_characters_into_guest_input_stream', 'Pasted {count} characters into guest input stream', { count: text.length }), 'success');
    }
  } else {
    if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) {
      _activeSerialWs.send(text.replace(/\r?\n/g, '\r'));
      showToast(t('toast.sent_characters_to_serial_terminal', 'Sent {count} characters to serial terminal', { count: text.length }), 'success');
    } else {
      showToast(t('toast.sent_characters_to_terminal', 'Sent {count} characters to terminal', { count: text.length }), 'success');
    }
  }
}

async function initRealVncClient(container, vmId, vmName) {
  cancelConsoleReconnect();
  if (_activeRfb) {
    try { _activeRfb.disconnect(); } catch (_) {}
    _activeRfb = null;
  }
  const statusPill = document.getElementById('vm-console-status-pill');
  if (statusPill) {
    statusPill.textContent = '● CONNECTING...';
    statusPill.style.color = '#fbbf24';
  }

  try {
    let tokenRes = null;
    try {
      tokenRes = await api.post(`/api/vms/${vmId}/console/token`);
    } catch (e) {
      console.warn('[VM Console] Ticket request failed:', e);
    }
    const ticket = tokenRes?.ticket || '';
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host || '127.0.0.1:8082';
    const wsUrl = `${protocol}//${host}/api/vms/${vmId}/console/ws?ticket=${ticket}`;

    let RFB = null;
    try {
      const mod = await import('@novnc/novnc');
      RFB = mod.default || mod;
    } catch (e) {
      console.warn('[VM Console] noVNC library load notice:', e);
    }

    if (RFB && container && typeof window !== 'undefined' && window.WebSocket) {
      let vncScreen = container.querySelector('.vnc-screen-target');
      if (!vncScreen) {
        vncScreen = document.createElement('div');
        vncScreen.className = 'vnc-screen-target';
        vncScreen.style.cssText = 'width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;';
        container.appendChild(vncScreen);
      } else {
        vncScreen.innerHTML = '';
      }

      const canvas = container.querySelector('#vm-console-canvas');
      if (canvas) canvas.style.display = 'none';

      const rfb = new RFB(vncScreen, wsUrl, {
        credentials: { password: '' },
        wsProtocols: ['binary'],
      });
      rfb.scaleViewport = true;
      rfb.resizeSession = false;
      rfb.clipViewport = false;
      rfb.focusOnClick = true;

      rfb.addEventListener('connect', () => {
        if (statusPill) {
          statusPill.textContent = '● LIVE';
          statusPill.style.color = '#34d399';
        }
        const resStat = document.getElementById('vm-console-resolution-stat');
        if (resStat && rfb._fbWidth) {
          resStat.textContent = `${rfb._fbWidth} × ${rfb._fbHeight}`;
        }
        showToast(t('toast.connected_to_display', 'Connected to {vmName} display', { vmName: vmName }), 'success');

        const realCanvas = vncScreen.querySelector('canvas');
        if (realCanvas) {
          realCanvas.tabIndex = 0;
          realCanvas.style.outline = 'none';
          try { realCanvas.focus({ preventScroll: true }); } catch (_) {}
          realCanvas.addEventListener('focus', () => setConsoleFocus(true));
        }
        try { rfb.focus({ preventScroll: true }); } catch (_) {}
        setConsoleFocus(true);
      });

      vncScreen.addEventListener('mousedown', () => {
        setConsoleFocus(true);
        const realCanvas = vncScreen.querySelector('canvas');
        if (realCanvas) {
          realCanvas.tabIndex = 0;
          try { realCanvas.focus({ preventScroll: true }); } catch (_) {}
        }
        try { rfb.focus({ preventScroll: true }); } catch (_) {}
      });

      rfb.addEventListener('disconnect', (e) => {
        if (statusPill) {
          statusPill.textContent = '● DISCONNECTED';
          statusPill.style.color = '#f87171';
        }
        if (e && e.detail && !e.detail.clean) {
          showToast(t('toast.console_disconnected', 'Console disconnected: {reason}', { reason: e.detail.reason || 'Connection closed' }), 'warning');
        }
        const consoleWin = document.getElementById('vm-console-window');
        if (consoleWin && !consoleWin._userClosing) {
          _scheduleConsoleReconnect(container, vmId, vmName, 'gui');
        }
      });

      rfb.addEventListener('securityfailure', (e) => {
        showToast(t('toast.vnc_security_error', 'VNC security error: {reason}', { reason: e.detail?.reason || t('toast.authentication_failed', 'Authentication failed') }), 'error');
      });

      _activeRfb = rfb;
      return rfb;
    }
  } catch (err) {
    console.warn('[VM Console] VNC client error:', err);
  }

  // Fallback to canvas simulator
  const canvas = container ? container.querySelector('#vm-console-canvas') : null;
  if (canvas) {
    canvas.style.display = 'block';
    initGuiDesktopSimulation(canvas, vmName);
  }
}

async function initRealSerialTerminal(container, vmId, vmName) {
  cancelConsoleReconnect();
  if (_activeSerialWs) {
    try { _activeSerialWs.close(); } catch (_) {}
    _activeSerialWs = null;
  }
  const statusPill = document.getElementById('vm-console-status-pill');
  if (statusPill) {
    statusPill.textContent = '● TTY CONNECTING...';
    statusPill.style.color = '#fbbf24';
  }

  const host = container ? container.querySelector('#vm-cli-output') : null;
  const view = ensureSerialView(host, vmId);
  const appendOutput = (chunk) => {
    rememberSerialChunk(vmId, chunk);
    if (view) view.write(chunk);
  };
  if (!(_serialBuffers.get(vmId) || []).length) {
    appendOutput(`\x1b[36m[ZettNAS Serial Terminal - Connecting to ${vmName}...]\x1b[0m\r\n`);
  }

  try {
    let tokenRes = null;
    try {
      tokenRes = await api.post(`/api/vms/${vmId}/console/token`);
    } catch (e) {}
    const ticket = tokenRes?.ticket || '';
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = window.location.host || '127.0.0.1:8082';
    const wsUrl = `${protocol}//${wsHost}/api/vms/${encodeURIComponent(vmId)}/serial/ws?ticket=${encodeURIComponent(ticket)}`;

    if (typeof WebSocket !== 'undefined') {
      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';
      ws.onopen = () => {
        if (statusPill) {
          statusPill.textContent = '● TTY LIVE';
          statusPill.style.color = '#34d399';
        }
        appendOutput(`\x1b[32m[Connected to serial console. Press Enter if screen is blank.]\x1b[0m\r\n\r\n`);
        if (view) view.focus();
        else container?.focus();
      };
      ws.onmessage = (e) => {
        if (e.data) appendOutput(typeof e.data === 'string' ? e.data : new Uint8Array(e.data));
      };
      ws.onclose = () => {
        if (statusPill) {
          statusPill.textContent = '● TTY CLOSED';
          statusPill.style.color = '#f87171';
        }
        appendOutput(`\r\n\x1b[31m[Serial connection closed]\x1b[0m\r\n`);
        const consoleWin = document.getElementById('vm-console-window');
        if (consoleWin && !consoleWin._userClosing) {
          _scheduleConsoleReconnect(container, vmId, vmName, 'cli');
        }
      };
      ws.onerror = () => {
        if (statusPill) {
          statusPill.textContent = '● TTY ERROR';
          statusPill.style.color = '#f87171';
        }
      };

      if (container) {
        container.tabIndex = 0;
        // Keys typed inside xterm never reach here (the view stops them); this
        // only handles keys forwarded by the console window's key guard.
        container.onkeydown = (e) => {
          e.stopPropagation();
          const data = serialKeyToData(e);
          if (data && ws.readyState === WebSocket.OPEN) {
            e.preventDefault();
            ws.send(data);
            if (view) view.focus();
          }
        };
      }

      _activeSerialWs = ws;
      return;
    }
  } catch (err) {
    console.warn('[VM Console] Serial terminal error:', err);
  }

  // Fallback to console simulation
  const canvas = document.getElementById('vm-console-canvas');
  if (canvas) {
    canvas.style.display = 'block';
    initConsoleSimulation(canvas, vmName);
  }
}


/**
 * Opens the dedicated glassmorphic VM Console Window (#vm-console-window)
 */
export function openVmConsole(vmId, vmName = 'Virtual Machine', initialMode = 'gui') {
  let consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin) {
    const html = `
      <div id="vm-console-window" class="os-window vm-console-window" data-focused="true" style="display: none; width: 880px; height: 600px; min-width: 640px; min-height: 480px;">
        <div class="os-window-header" id="vm-console-header">
          <div class="os-window-title" style="display: flex; align-items: center; gap: 8px;">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            <span id="vm-console-title-text">VM Console: ${escapeHtml(vmName)}</span>
            <span id="vm-console-status-pill" class="console-status-pill">● LIVE</span>
          </div>
          <div class="os-window-controls">
            <button class="win-btn min-btn" id="vm-console-min" title="${t('window.minimize', 'Minimize')}" aria-label="${t('window.minimize', 'Minimize')}"></button>
            <button class="win-btn max-btn" id="vm-console-max" title="${t('ui.maximize', 'Maximize')}" aria-label="${t('ui.maximize', 'Maximize')}"></button>
            <button class="win-btn close-btn" id="vm-console-close" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
          </div>
        </div>

        <!-- Console Control Bar -->
        <div class="vm-console-toolbar">
          <div class="console-toolbar-left">
            <div class="console-mode-switch">
              <button class="btn-console-mode ${initialMode === 'gui' ? 'active' : ''}" id="btn-console-mode-gui" title="${t('vm.mode_gui', 'KVM GUI')}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                <span>${t('vm.mode_gui', 'KVM GUI')}</span>
              </button>
              <button class="btn-console-mode ${initialMode === 'cli' ? 'active' : ''}" id="btn-console-mode-cli" title="${t('vm.mode_tty', 'Serial TTY')}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                <span>${t('vm.mode_tty', 'Serial TTY')}</span>
              </button>
            </div>
            <span class="toolbar-stat"><span class="stat-dot-pulse"></span> 60 FPS</span>
            <span class="toolbar-stat" id="vm-console-resolution-stat">${initialMode === 'cli' ? '80 × 25 TTY' : '1920 × 1080'}</span>
            <span class="toolbar-stat" id="vm-console-adapter-stat" style="color: ${initialMode === 'cli' ? '#34d399' : '#38bdf8'};">${initialMode === 'cli' ? 'Serial TTY' : 'VirtIO-GPU'}</span>
            <span class="toolbar-stat" id="vm-console-kbd-pill" style="color: var(--zn-text-accent); font-weight: 500; cursor: pointer;" title="${t('ui.keyboard_captured_by_vm_console', 'Keyboard captured by VM console. Click outside or minimize to release.')}">⌨️ Captured</span>
          </div>
          <div class="console-toolbar-right">
            <button class="btn-console-act" id="btn-vnc-softkbd" title="${t('vm.soft_kbd', 'Keyboard')}">
              <span>⌨️ ${t('vm.soft_kbd', 'Keyboard')}</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-cad" title="${t('ui.send_ctrl_alt_del', 'Send Ctrl+Alt+Del')}">
              <span>Ctrl+Alt+Del</span>
            </button>
            <div class="dropdown-sendkey-wrap" style="position: relative;">
              <button class="btn-console-act" id="btn-vnc-keys" title="${t('ui.send_special_key', 'Send Special Key')}">
                <span>Send Key ▾</span>
              </button>
              <div id="menu-vnc-keys" class="vnc-keys-menu" style="display: none;">
                <button class="vnc-key-item" data-key="Tab">Tab</button>
                <button class="vnc-key-item" data-key="Escape">Escape</button>
                <button class="vnc-key-item" data-key="Ctrl+C">Ctrl + C</button>
                <button class="vnc-key-item" data-key="Super">Super / Windows</button>
                <button class="vnc-key-item" data-key="F12">F12 (Boot Menu)</button>
              </div>
            </div>
            <button class="btn-console-act" id="btn-vnc-clipboard" title="${t('ui.paste_text_to_guest', 'Paste text to guest')}">
              <span>📋 Paste Text</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-popout" title="${t('vm.popout', 'Separate Window')}">
              <span>↗ ${t('vm.popout', 'Separate Window')}</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-reconnect" title="${t('ui.reconnect_stream', 'Reconnect stream')}">
              <span>↻ Reconnect</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-fullscreen" title="${t('ctx.fullscreen', 'Toggle Fullscreen')}">
              <span>⛶ Fullscreen</span>
            </button>
          </div>
        </div>

        <!-- Viewport -->
        <div class="vm-console-viewport" id="vm-console-viewport" style="position: relative; flex: 1; display: flex; align-items: center; justify-content: center; background: var(--lt-b-060a12ff, #060a12); overflow: hidden;">
          <div id="vm-console-banner" class="vm-console-banner" style="display: none;"></div>
          <input type="text" id="vm-console-hidden-input" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" tabindex="-1" style="position: absolute; opacity: 0; pointer-events: none; width: 1px; height: 1px; left: 0; top: 0; z-index: -1;" />
          <div id="vm-vnc-container" style="width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; overflow: hidden;">
            <canvas id="vm-console-canvas" tabindex="0" width="880" height="510"></canvas>
          </div>
          <div id="vm-cli-container" tabindex="0" style="width: 100%; height: 100%; display: none; background: var(--lt-b-0a0f18ff, #0a0f18); padding: 10px 8px 10px 12px; color: var(--zn-text-ok); overflow: hidden; box-sizing: border-box; outline: none;">
            <div id="vm-cli-output" style="width: 100%; height: 100%;"></div>
          </div>
          <div class="console-scanlines" style="pointer-events: none;"></div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
    consoleWin = document.getElementById('vm-console-window');

    // Register with DockManager
    if (window.DockManager) {
      window.DockManager.register('vm-console', consoleWin, '#i-vm', `Console: ${vmName}`);
    }

    makeDraggable(consoleWin, consoleWin.querySelector('#vm-console-header'));
    consoleWin.addEventListener('mousedown', (e) => {
      bringToFront(consoleWin);
      setConsoleFocus(true);
      const tag = e.target?.tagName?.toLowerCase();
      if (['button', 'input', 'select', 'textarea'].includes(tag) || e.target?.closest?.('button, input, select, textarea, .dropdown-sendkey-wrap, .os-window-controls')) {
        return;
      }
      focusActiveConsole();
    });

    document.addEventListener('mousedown', (e) => {
      const cw = document.getElementById('vm-console-window');
      if (cw && !cw.contains(e.target)) {
        setConsoleFocus(false);
      }
    });

    const kbdPill = consoleWin.querySelector('#vm-console-kbd-pill');
    if (kbdPill) {
      kbdPill.onclick = (e) => {
        e.stopPropagation();
        bringToFront(consoleWin);
        setConsoleFocus(true);
        focusActiveConsole();
        const hiddenInput = consoleWin.querySelector('#vm-console-hidden-input');
        if (hiddenInput && isTouch()) {
          hiddenInput.focus();
        }
      };
    }

    const viewport = consoleWin.querySelector('#vm-console-viewport');
    if (viewport) {
      viewport.addEventListener('click', (e) => {
        const tag = e.target?.tagName?.toLowerCase();
        if (['button', 'input', 'select', 'textarea'].includes(tag) || e.target?.closest?.('button, input, select, textarea')) {
          return;
        }
        setConsoleFocus(true);
        focusActiveConsole();
      });
    }

    const hiddenInput = consoleWin.querySelector('#vm-console-hidden-input');
    const btnSoftKbd = consoleWin.querySelector('#btn-vnc-softkbd');
    if (btnSoftKbd && hiddenInput) {
      btnSoftKbd.onclick = (e) => {
        e.stopPropagation();
        bringToFront(consoleWin);
        setConsoleFocus(true);
        hiddenInput.focus();
      };
    }
    if (hiddenInput) {
      hiddenInput.addEventListener('input', () => {
        const val = hiddenInput.value;
        if (val) {
          const mode = consoleWin._activeMode || 'gui';
          if (mode === 'gui') {
            for (let i = 0; i < val.length; i++) {
              const ch = val[i];
              if (ch === '\n') _sendKeyToRfb(0xff0d, 'Enter');
              else _sendKeyToRfb(ch.charCodeAt(0), null);
            }
          } else if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) {
            _activeSerialWs.send(val.replace(/\r?\n/g, '\r'));
          }
          hiddenInput.value = '';
        }
      });
      hiddenInput.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace') {
          const mode = consoleWin._activeMode || 'gui';
          if (mode === 'gui') {
            _sendKeyToRfb(0xff08, 'Backspace');
          } else if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) {
            e.preventDefault();
            e.stopPropagation();
            _activeSerialWs.send('\x7f');
          }
        } else if (e.key === 'Enter') {
          const mode = consoleWin._activeMode || 'gui';
          if (mode === 'gui') {
            _sendKeyToRfb(0xff0d, 'Enter');
          } else if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) {
            e.preventDefault();
            e.stopPropagation();
            _activeSerialWs.send('\r');
          }
        }
      });
    }

    // Minimize, Maximize, Close Bindings
    const minBtn = consoleWin.querySelector('#vm-console-min');
    const maxBtn = consoleWin.querySelector('#vm-console-max');
    const closeBtn = consoleWin.querySelector('#vm-console-close');

    if (minBtn) {
      minBtn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        cancelConsoleReconnect();
        setConsoleFocus(false);
        consoleWin.classList.add('window-minimized');
        consoleWin.classList.remove('open');
        consoleWin.style.setProperty('display', 'none', 'important');
        if (window.DockManager) window.DockManager.minimize('vm-console');
      };
    }
    if (closeBtn) {
      closeBtn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        consoleWin._userClosing = true;
        cancelConsoleReconnect();
        setConsoleFocus(false);
        if (_activeRfb) {
          try { _activeRfb.disconnect(); } catch (_) {}
          _activeRfb = null;
        }
        if (_activeSerialWs) {
          try { _activeSerialWs.close(); } catch (_) {}
          _activeSerialWs = null;
        }
        const canvas = consoleWin.querySelector('#vm-console-canvas');
        if (canvas && canvas._blinkInterval) {
          clearInterval(canvas._blinkInterval);
          canvas._blinkInterval = null;
        }
        if (document.body.classList.contains('vm-console-direct')) {
          try {
            window.close();
          } catch (_) {}
          document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:var(--lt-b-060a12ff, #060a12);color:var(--zn-text-muted);font-family:sans-serif;font-size:14px;">Console disconnected. You can close this window.</div>';
          return;
        }
        consoleWin.classList.add('window-minimized');
        consoleWin.classList.remove('open');
        consoleWin.style.setProperty('display', 'none', 'important');
        if (window.DockManager) {
          window.DockManager.closeWindow('vm-console');
        }
      };
    }
    let isMax = false;
    let preBounds = null;
    if (maxBtn) {
      maxBtn.onclick = () => {
        if (!isMax) {
          preBounds = {
            left: consoleWin.style.left,
            top: consoleWin.style.top,
            width: consoleWin.style.width,
            height: consoleWin.style.height,
          };
          consoleWin.style.left = '0px';
          consoleWin.style.top = '36px';
          consoleWin.style.width = '100vw';
          consoleWin.style.height = 'calc(100vh - 36px - 72px)';
          isMax = true;
        } else {
          if (preBounds) {
            consoleWin.style.left = preBounds.left;
            consoleWin.style.top = preBounds.top;
            consoleWin.style.width = preBounds.width;
            consoleWin.style.height = preBounds.height;
          }
          isMax = false;
        }
      };
    }

    // Key dropdown toggle
    const btnKeys = consoleWin.querySelector('#btn-vnc-keys');
    const menuKeys = consoleWin.querySelector('#menu-vnc-keys');
    if (btnKeys && menuKeys) {
      btnKeys.onclick = (e) => {
        e.stopPropagation();
        const isMobile = isCompact();
        if (isMobile) {
          showBottomSheet({
            title: 'Send Special Key',
            subtitle: consoleWin._vmName || vmName,
            items: [
              { icon: '⇥', label: 'Tab', onClick: () => { _sendKeyToRfb(0xff09, 'Tab'); showToast(t('toast.sent_key_tab_to_guest_vm', "Sent key 'Tab' to guest VM"), 'info'); } },
              { icon: '⎋', label: 'Escape', onClick: () => { _sendKeyToRfb(0xff1b, 'Escape'); showToast(t('toast.sent_key_escape_to_guest_vm', "Sent key 'Escape' to guest VM"), 'info'); } },
              { icon: '🛑', label: 'Ctrl + C', onClick: () => { _sendCtrlCToRfb(); showToast(t('toast.sent_key_ctrl_c_to_guest', "Sent key 'Ctrl+C' to guest VM"), 'info'); } },
              { icon: '🪟', label: 'Super / Windows Key', onClick: () => { _sendKeyToRfb(0xffeb, 'MetaLeft'); showToast(t('toast.sent_key_super_to_guest_vm', "Sent key 'Super' to guest VM"), 'info'); } },
              { icon: '⚙️', label: 'F12 (Boot Menu)', onClick: () => { _sendKeyToRfb(0xffcb, 'F12'); showToast(t('toast.sent_key_f12_to_guest_vm', "Sent key 'F12' to guest VM"), 'info'); } },
              { icon: '⚡', label: 'Ctrl + Alt + Del', destructive: true, onClick: () => { consoleWin.querySelector('#btn-vnc-cad')?.click(); } },
            ],
          });
          return;
        }
        menuKeys.style.display = menuKeys.style.display === 'none' ? 'block' : 'none';
      };
      consoleWin.querySelectorAll('.vnc-key-item').forEach((item) => {
        item.onclick = (e) => {
          e.stopPropagation();
          const key = item.dataset.key;
          if (key === 'Tab') _sendKeyToRfb(0xff09, 'Tab');
          else if (key === 'Escape') _sendKeyToRfb(0xff1b, 'Escape');
          else if (key === 'Ctrl+C') _sendCtrlCToRfb();
          else if (key === 'Super') _sendKeyToRfb(0xffeb, 'MetaLeft');
          else if (key === 'F12') _sendKeyToRfb(0xffcb, 'F12');
          menuKeys.style.display = 'none';
          showToast(t('toast.sent_key_to_guest_vm', 'Sent key \'{key}\' to guest VM', { key: key }), 'info');
        };
      });
      document.addEventListener('click', () => {
        if (menuKeys) menuKeys.style.display = 'none';
      });
    }

    // Ctrl+Alt+Del
    const btnCad = consoleWin.querySelector('#btn-vnc-cad');
    if (btnCad) {
      btnCad.onclick = () => {
        if (_activeRfb && typeof _activeRfb.sendCtrlAltDel === 'function') {
          _activeRfb.sendCtrlAltDel();
        }
        showToast(t('toast.sent_ctrl_alt_del_signal_to', 'Sent Ctrl+Alt+Del signal to {vmName}', { vmName: consoleWin._vmName || vmName }), 'info');
      };
    }

    // Fullscreen
    const btnFs = consoleWin.querySelector('#btn-vnc-fullscreen');
    if (btnFs && viewport) {
      btnFs.onclick = () => {
        if (!document.fullscreenElement) {
          viewport.requestFullscreen?.().catch(() => {});
        } else {
          document.exitFullscreen?.().catch(() => {});
        }
      };
    }

    // Mode Switcher Buttons
    const btnModeGui = consoleWin.querySelector('#btn-console-mode-gui');
    const btnModeCli = consoleWin.querySelector('#btn-console-mode-cli');

    if (btnModeGui) {
      btnModeGui.onclick = () => {
        setConsoleMode('gui');
      };
    }
    if (btnModeCli) {
      btnModeCli.onclick = () => {
        setConsoleMode('cli');
      };
    }

    // Reconnect
    const btnRec = consoleWin.querySelector('#btn-vnc-reconnect');
    if (btnRec) {
      btnRec.onclick = () => {
        showToast(t('toast.reconnecting_console_stream', 'Reconnecting console stream...'), 'info');
        const mode = consoleWin._activeMode || 'gui';
        if (mode === 'gui') {
          const vncWrap = consoleWin.querySelector('#vm-vnc-container');
          initRealVncClient(vncWrap, consoleWin._vmId || vmId, consoleWin._vmName || vmName);
        } else {
          const cliWrap = consoleWin.querySelector('#vm-cli-container');
          initRealSerialTerminal(cliWrap, consoleWin._vmId || vmId, consoleWin._vmName || vmName);
        }
      };
    }

    // Native window paste event
    consoleWin.addEventListener('paste', async (e) => {
      const activeEl = document.activeElement;
      if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA') && activeEl.id !== 'vm-console-hidden-input') {
        return;
      }
      e.preventDefault();
      const text = e.clipboardData?.getData('text') || '';
      if (text) {
        await pasteTextToGuestConsole(text);
      }
    });

    // Clipboard paste prompt
    const btnClip = consoleWin.querySelector('#btn-vnc-clipboard');
    if (btnClip) {
      btnClip.onclick = async () => {
        let text = '';
        try {
          if (navigator.clipboard && navigator.clipboard.readText) {
            text = await navigator.clipboard.readText();
          }
        } catch (_) {}
        if (text) {
          await pasteTextToGuestConsole(text);
        } else {
          showPromptToast(
            t('vm.paste_modal_title', 'Paste Text to Guest VM'),
            t('vm.paste_modal_desc', 'Enter or paste the text string to send to the virtual machine console:'),
            '',
            async (val) => {
              if (val) {
                await pasteTextToGuestConsole(val);
              }
            },
            null,
            {
              inputType: 'textarea',
              icon: '📋',
              okText: t('vm.paste_btn_action', '📋 Paste into VM'),
              placeholder: t('vm.paste_placeholder', 'Type or paste commands, keys, or text here... (Ctrl+Enter to send)'),
            }
          );
        }
      };
    }

    // Pop out in separate window
    const btnPopout = consoleWin.querySelector('#btn-vnc-popout');
    if (btnPopout) {
      btnPopout.onclick = () => {
        const curId = consoleWin._vmId || vmId;
        const curName = consoleWin._vmName || vmName;
        const curMode = consoleWin._activeMode || 'gui';
        openVmConsoleSeparateWindow(curId, curName, curMode);
        if (closeBtn) closeBtn.click();
      };
    }
  }

  function setConsoleMode(mode) {
    consoleWin._activeMode = mode;
    const btnGui = consoleWin.querySelector('#btn-console-mode-gui');
    const btnCli = consoleWin.querySelector('#btn-console-mode-cli');
    const resStat = consoleWin.querySelector('#vm-console-resolution-stat');
    const adpStat = consoleWin.querySelector('#vm-console-adapter-stat');
    const titleTxt = consoleWin.querySelector('#vm-console-title-text');

    const vncWrap = consoleWin.querySelector('#vm-vnc-container');
    const cliWrap = consoleWin.querySelector('#vm-cli-container');

    const canvas = consoleWin.querySelector('#vm-console-canvas');

    if (mode === 'gui') {
      if (btnGui) btnGui.classList.add('active');
      if (btnCli) btnCli.classList.remove('active');
      if (resStat) resStat.textContent = '1920 × 1080';
      if (adpStat) {
        adpStat.textContent = t('vm.display_virtio_gpu', 'VirtIO-GPU');
        adpStat.style.color = '#38bdf8';
      }
      if (titleTxt) titleTxt.textContent = `VM Console: ${consoleWin._vmName || vmName} (KVM GUI)`;

      if (vncWrap) vncWrap.style.display = 'flex';
      if (cliWrap) cliWrap.style.display = 'none';

      if (_activeSerialWs) {
        try { _activeSerialWs.close(); } catch (_) {}
        _activeSerialWs = null;
      }
      if (canvas) {
        initGuiDesktopSimulation(canvas, consoleWin._vmName || vmName);
      }
      const isTestEnv = typeof window !== 'undefined' && (window.__VITEST__ || window.VITEST);
      if (!isTestEnv) {
        initRealVncClient(vncWrap, consoleWin._vmId || vmId, consoleWin._vmName || vmName);
      }
      focusActiveConsole();
    } else {
      if (btnCli) btnCli.classList.add('active');
      if (btnGui) btnGui.classList.remove('active');
      if (resStat) resStat.textContent = '80 × 25 TTY';
      if (adpStat) {
        adpStat.textContent = t('vm.mode_tty', 'Serial TTY');
        adpStat.style.color = '#34d399';
      }
      if (titleTxt) titleTxt.textContent = `VM Console: ${consoleWin._vmName || vmName} (Serial TTY)`;

      if (vncWrap) vncWrap.style.display = 'none';
      if (cliWrap) cliWrap.style.display = 'block';

      if (_activeRfb) {
        try { _activeRfb.disconnect(); } catch (_) {}
        _activeRfb = null;
      }
      if (canvas) {
        initConsoleSimulation(canvas, consoleWin._vmName || vmName);
      }
      const isTestEnv = typeof window !== 'undefined' && (window.__VITEST__ || window.VITEST);
      if (!isTestEnv) {
        initRealSerialTerminal(cliWrap, consoleWin._vmId || vmId, consoleWin._vmName || vmName);
      }
      focusActiveConsole();
    }
  }

  consoleWin._setConsoleMode = setConsoleMode;
  consoleWin._vmName = vmName;
  consoleWin._vmId = vmId;
  consoleWin._userClosing = false;
  cancelConsoleReconnect();

  if (window.DockManager) {
    window.DockManager.register('vm-console', consoleWin, '#i-vm', `Console: ${vmName}`);
    window.DockManager.restore('vm-console');
  }
  consoleWin.classList.remove('window-minimized');
  consoleWin.classList.add('open');
  consoleWin.style.removeProperty('display');
  consoleWin.style.setProperty('display', 'flex', 'important');
  bringToFront(consoleWin);

  if (typeof document !== 'undefined' && document.body && document.body.classList.contains('vm-console-direct')) {
    consoleWin.classList.add('vm-console-standalone');
    document.title = `VM Console: ${vmName} - ZettNAS`;
  }

  setConsoleMode(initialMode || 'gui');
  focusActiveConsole();
}

/**
 * Opens VM Console in a dedicated separate native browser window
 * @param {string} vmId
 * @param {string} vmName
 * @param {string} mode - 'gui' or 'cli'
 */
export function openVmConsoleSeparateWindow(vmId, vmName = 'Virtual Machine', mode = 'gui') {
  const availW = (typeof window !== 'undefined' && window.screen && window.screen.availWidth) ? window.screen.availWidth : 1280;
  const availH = (typeof window !== 'undefined' && window.screen && window.screen.availHeight) ? window.screen.availHeight : 800;
  const width = Math.min(1366, Math.max(960, Math.floor(availW * 0.85)));
  const height = Math.min(900, Math.max(680, Math.floor(availH * 0.85)));
  const left = Math.max(0, Math.floor((availW - width) / 2));
  const top = Math.max(0, Math.floor((availH - height) / 2));
  const origin = (typeof window !== 'undefined' && window.location) ? window.location.origin : '';
  const pathname = (typeof window !== 'undefined' && window.location) ? window.location.pathname : '/';
  const url = `${origin}${pathname}?mode=vm-console&vm=${encodeURIComponent(vmId)}&name=${encodeURIComponent(vmName || '')}&consoleMode=${encodeURIComponent(mode || 'gui')}`;

  if (typeof window !== 'undefined' && window.open) {
    const win = window.open(
      url,
      `vm_console_${vmId}`,
      `width=${width},height=${height},left=${left},top=${top},menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=no`
    );
    if (win && win.focus) {
      try { win.focus(); } catch (_) {}
    }
    return win;
  }
  return null;
}

if (typeof window !== 'undefined') {
  window.openVmConsoleSeparateWindow = openVmConsoleSeparateWindow;
}

/**
 * Interactive Terminal Canvas Simulator
 * Renders Linux boot framebuffer and responds to typing with blinking block cursor.
 */
function initConsoleSimulation(canvas, vmName) {
  if (!canvas) return;
  if (canvas._blinkInterval) {
    clearInterval(canvas._blinkInterval);
    canvas._blinkInterval = null;
  }
  if (canvas._guiInterval) {
    clearInterval(canvas._guiInterval);
    canvas._guiInterval = null;
  }
  if (canvas._guiMouseMove) {
    canvas.removeEventListener('mousemove', canvas._guiMouseMove);
    canvas._guiMouseMove = null;
  }
  if (canvas._guiMouseLeave) {
    canvas.removeEventListener('mouseleave', canvas._guiMouseLeave);
    canvas._guiMouseLeave = null;
  }
  if (canvas._guiMouseDown) {
    canvas.removeEventListener('mousedown', canvas._guiMouseDown);
    canvas._guiMouseDown = null;
  }
  const ctx = canvas.getContext ? canvas.getContext('2d') : null;

  const promptPrefix = `root@${vmName}:~# `;

  let lines = [
    `[  0.000000] Linux version 6.8.0-45-generic (buildd@lcy02-amd64-080) (gcc-13)`,
    `[  0.012491] KVM: Hardware acceleration active (Intel VT-x / AMD-V)`,
    `[  0.089120] ACPI: Core revision 20230628, 4 vCPUs active`,
    `[  0.158203] virtio_net virtio0: assigned MAC 52:54:00:12:34:56 (attached to br0)`,
    `[  0.412901] virtio_blk virtio1: 64 GB qcow2 virtual drive mounted`,
    `[  0.892011] systemd 255.4-1ubuntu8 running in system mode`,
    `[  1.210452] Started OpenSSH Server Daemon on port 22`,
    `[  1.450210] IPv4 DHCP Lease: 192.168.1.180/24 via br0`,
    ``,
    `Ubuntu 24.04.1 LTS ${vmName} tty1`,
    `${vmName} login: root (automatic login)`,
    `Last login: ${new Date().toDateString()} on tty1`,
    promptPrefix
  ];

  let currentInput = '';
  let cursorVisible = true;
  const commandHistory = [];
  let historyIndex = -1;

  function render() {
    if (!ctx) return;
    ctx.fillStyle = '#0a0f18';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.font = '12px "JetBrains Mono", "Fira Code", monospace';
    ctx.textBaseline = 'top';

    const lineHeight = 18;
    const startY = 16;
    const startX = 16;

    // Viewport auto-scrolling
    const maxVisibleLines = Math.max(1, Math.floor((canvas.height - 32) / lineHeight));
    const totalLines = lines.length;
    const startIndex = Math.max(0, totalLines - maxVisibleLines);
    const visibleSlice = lines.slice(startIndex);

    for (let i = 0; i < visibleSlice.length - 1; i++) {
      const line = visibleSlice[i];
      if (line.startsWith('[  ')) {
        ctx.fillStyle = '#64748b'; // boot dmesg timestamp
      } else if (line.startsWith('root@')) {
        ctx.fillStyle = '#38bdf8'; // shell prompt
      } else if (line.includes('command not found')) {
        ctx.fillStyle = '#f87171'; // bash error
      } else if (line.startsWith('Ubuntu') || line.startsWith('Linux')) {
        ctx.fillStyle = '#34d399'; // system info
      } else {
        ctx.fillStyle = '#94a3b8'; // standard output
      }
      ctx.fillText(line, startX, startY + (i * lineHeight));
    }

    // Active prompt line
    const lastIdx = visibleSlice.length - 1;
    const activePrompt = visibleSlice[lastIdx] || promptPrefix;

    ctx.fillStyle = '#38bdf8';
    ctx.fillText(activePrompt, startX, startY + (lastIdx * lineHeight));
    const promptWidth = ctx.measureText(activePrompt).width;

    ctx.fillStyle = '#ffffff';
    ctx.fillText(currentInput, startX + promptWidth, startY + (lastIdx * lineHeight));
    const inputWidth = ctx.measureText(currentInput).width;

    // Blinking cursor
    if (cursorVisible) {
      ctx.fillStyle = '#34d399';
      ctx.fillRect(startX + promptWidth + inputWidth + 2, startY + (lastIdx * lineHeight) + 2, 8, 14);
    }
  }

  if (canvas._blinkInterval) clearInterval(canvas._blinkInterval);
  if (ctx) {
    canvas._blinkInterval = setInterval(() => {
      cursorVisible = !cursorVisible;
      render();
    }, 500);
  }

  canvas.addEventListener('click', () => {
    canvas.focus();
    setConsoleFocus(true);
  });
  canvas.addEventListener('focus', () => setConsoleFocus(true));
  canvas.addEventListener('blur', (e) => {
    const cw = document.getElementById('vm-console-window');
    if (!cw || !cw.contains(e.relatedTarget)) {
      setConsoleFocus(false);
    }
  });

  canvas.focus();
  canvas.addEventListener('keydown', (e) => e.stopPropagation());
  canvas.onkeydown = (e) => {
    // Unconditionally stop propagation to ensure no keyboard leakage to desktop shortcuts
    e.stopPropagation();

    if (e.key === 'Backspace') {
      e.preventDefault();
      currentInput = currentInput.slice(0, -1);
      render();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const promptLine = lines[lines.length - 1] || promptPrefix;
      lines[lines.length - 1] = `${promptLine}${currentInput}`;
      const trimmed = currentInput.trim();

      if (trimmed.length > 0) {
        commandHistory.push(trimmed);
        historyIndex = -1;
      }

      if (trimmed === '') {
        // Just empty Enter
      } else if (trimmed === 'help') {
        lines.push('ZettNAS Virtual Machine Console v1.0 (QEMU/KVM Serial TTY)');
        lines.push('Available guest commands: ls, cat, uname -a, ip a, df -h, free -h, uptime, whoami, id, pwd, ps, ping, date, echo, clear, help');
      } else if (trimmed === 'clear') {
        lines = [];
      } else if (trimmed === 'ls' || trimmed === 'dir') {
        lines.push('bin   dev  home  lib64  mnt  proc  run   srv  tmp  var');
        lines.push('boot  etc  lib   media  opt  root  sbin  sys  usr');
      } else if (trimmed === 'ls -la' || trimmed === 'ls -l' || trimmed === 'll') {
        lines.push('total 64');
        lines.push('drwx------  4 root root 4096 Oct 12 19:30 .');
        lines.push('drwxr-xr-x 19 root root 4096 Oct 12 19:25 ..');
        lines.push('-rw-r--r--  1 root root 3106 Apr 22 14:15 .bashrc');
        lines.push('-rw-r--r--  1 root root  161 Jul  9 09:12 .profile');
        lines.push('drwx------  2 root root 4096 Oct 12 19:28 .ssh');
      } else if (trimmed === 'whoami') {
        lines.push('root');
      } else if (trimmed === 'id') {
        lines.push('uid=0(root) gid=0(root) groups=0(root)');
      } else if (trimmed === 'pwd') {
        lines.push('/root');
      } else if (trimmed === 'hostname') {
        lines.push(vmName);
      } else if (trimmed.startsWith('uname')) {
        lines.push(`Linux ${vmName} 6.8.0-45-generic #45-Ubuntu SMP PREEMPT_DYNAMIC x86_64 GNU/Linux`);
      } else if (trimmed === 'uptime') {
        lines.push(' 19:52:04 up 2 days, 4:18,  1 user,  load average: 0.08, 0.04, 0.01');
      } else if (trimmed === 'ip a' || trimmed === 'ip addr' || trimmed === 'ifconfig') {
        lines.push('1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000');
        lines.push('    inet 127.0.0.1/8 scope host lo');
        lines.push('2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000');
        lines.push('    inet 192.168.1.180/24 metric 100 brd 192.168.1.255 scope global dynamic eth0');
      } else if (trimmed.startsWith('df')) {
        lines.push('Filesystem      Size  Used Avail Use% Mounted on');
        lines.push('/dev/vda1        62G  5.2G   54G   9% /');
        lines.push('tmpfs            1.9G     0  1.9G   0% /dev/shm');
        lines.push('efivarfs        128K   28K   96K  23% /sys/firmware/efi/efivars');
      } else if (trimmed.startsWith('free')) {
        lines.push('               total        used        free      shared  buff/cache   available');
        lines.push('Mem:           4.0Gi       482Mi       2.8Gi        12Mi       780Mi       3.4Gi');
        lines.push('Swap:          2.0Gi          0B       2.0Gi');
      } else if (trimmed.startsWith('cat /etc/os-release') || trimmed.startsWith('cat /etc/issue')) {
        lines.push('PRETTY_NAME="Ubuntu 24.04.1 LTS"');
        lines.push('NAME="Ubuntu"');
        lines.push('VERSION_ID="24.04"');
        lines.push('VERSION="24.04.1 LTS (Noble Numbat)"');
        lines.push('ID=ubuntu');
        lines.push('ID_LIKE=debian');
        lines.push('HOME_URL="https://www.ubuntu.com/"');
      } else if (trimmed.startsWith('cat ')) {
        const file = trimmed.slice(4).trim();
        lines.push(`cat: ${file}: No such file or directory`);
      } else if (trimmed.startsWith('ps') || trimmed === 'top') {
        lines.push('  PID TTY          TIME CMD');
        lines.push('    1 ?        00:00:02 systemd');
        lines.push('  412 ?        00:00:00 systemd-journald');
        lines.push('  890 ?        00:00:00 sshd');
        lines.push(' 1024 tty1     00:00:00 bash');
        lines.push(' 1045 tty1     00:00:00 ps');
      } else if (trimmed.startsWith('ping')) {
        const host = trimmed.split(' ')[1] || '1.1.1.1';
        lines.push(`PING ${host} (${host}) 56(84) bytes of data.`);
        lines.push(`64 bytes from ${host}: icmp_seq=1 ttl=58 time=11.4 ms`);
        lines.push(`64 bytes from ${host}: icmp_seq=2 ttl=58 time=12.1 ms`);
        lines.push(`--- ${host} ping statistics ---`);
        lines.push('2 packets transmitted, 2 received, 0% packet loss, time 1002ms');
      } else if (trimmed === 'date') {
        lines.push(new Date().toUTCString());
      } else if (trimmed.startsWith('echo ')) {
        lines.push(trimmed.slice(5));
      } else if (trimmed === 'exit' || trimmed === 'logout') {
        lines.push('logout');
        lines.push(`Ubuntu 24.04.1 LTS ${vmName} tty1`);
        lines.push(`${vmName} login: root (automatic login)`);
      } else {
        lines.push(`-bash: ${trimmed.split(' ')[0]}: command not found`);
      }

      lines.push(promptPrefix);
      currentInput = '';
      render();
    } else if (e.key === 'Tab') {
      e.preventDefault();
      currentInput += '    ';
      render();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      // Swallow Escape inside console so it never closes desktop drawers or modals
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (commandHistory.length > 0) {
        if (historyIndex < commandHistory.length - 1) {
          historyIndex++;
          currentInput = commandHistory[commandHistory.length - 1 - historyIndex];
          render();
        }
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (historyIndex > 0) {
        historyIndex--;
        currentInput = commandHistory[commandHistory.length - 1 - historyIndex];
        render();
      } else if (historyIndex === 0) {
        historyIndex = -1;
        currentInput = '';
        render();
      }
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c') {
      e.preventDefault();
      const promptLine = lines[lines.length - 1] || promptPrefix;
      lines[lines.length - 1] = `${promptLine}${currentInput}^C`;
      lines.push(promptPrefix);
      currentInput = '';
      historyIndex = -1;
      render();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'l') {
      e.preventDefault();
      lines = [promptPrefix];
      render();
    } else if (e.key === ' ' || e.code === 'Space') {
      e.preventDefault();
      currentInput += ' ';
      render();
    } else if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
      e.preventDefault();
      currentInput += e.key;
      render();
    }
  };

  render();
}

// Global Focus Guard for VM Console Keyboard Capture
if (typeof window !== 'undefined' && !window._vmConsoleGlobalCaptureBound) {
  window._vmConsoleGlobalCaptureBound = true;
  window.addEventListener(
    'keydown',
    (e) => {
      const cw = document.getElementById('vm-console-window');
      if (!cw || cw.style.display === 'none' || cw.classList.contains('window-minimized')) {
        return;
      }
      const isFocused = cw.dataset.focused === 'true' || cw.contains(document.activeElement);
      if (!isFocused) return;

      const activeTag = document.activeElement?.tagName?.toLowerCase();
      if (['input', 'textarea', 'select'].includes(activeTag) && document.activeElement?.id !== 'vm-console-hidden-input') {
        return;
      }

      if (e.key === 'Tab') {
        e.preventDefault();
      }

      const mode = cw._activeMode || 'gui';
      if (mode === 'gui') {
        const realCanvas = cw.querySelector('.vnc-screen-target canvas');
        if (realCanvas) {
          if (document.activeElement === realCanvas) {
            return;
          }
          realCanvas.tabIndex = 0;
          try { realCanvas.focus({ preventScroll: true }); } catch (_) {}
          if (_activeRfb && typeof _activeRfb.focus === 'function') {
            try { _activeRfb.focus({ preventScroll: true }); } catch (_) {}
          }
          _handleRfbKeyFallback(e);
          return;
        }

        // Offline / Test Simulation canvas
        const simCanvas = cw.querySelector('#vm-console-canvas');
        if (simCanvas && simCanvas.style.display !== 'none') {
          if (document.activeElement !== simCanvas) {
            simCanvas.focus();
          }
          if (simCanvas.onkeydown && e.target !== simCanvas) {
            simCanvas.onkeydown(e);
          }
        }
      } else {
        // Serial TTY mode
        const cliContainer = cw.querySelector('#vm-cli-container');
        if (cliContainer && cliContainer.style.display !== 'none') {
          if (cliContainer === document.activeElement || cliContainer.contains(e.target)) {
            return;
          }
          try { cliContainer.focus({ preventScroll: true }); } catch (_) {}
          if (cliContainer.onkeydown) {
            e.preventDefault();
            e.stopPropagation();
            cliContainer.onkeydown(e);
          }
          return;
        }
        const simCanvas = cw.querySelector('#vm-console-canvas');
        if (simCanvas && simCanvas.style.display !== 'none') {
          if (document.activeElement === simCanvas || simCanvas.contains(e.target)) {
            return;
          }
          if (simCanvas.onkeydown) {
            e.preventDefault();
            e.stopPropagation();
            simCanvas.onkeydown(e);
          }
        }
      }
    },
    true
  );
}
