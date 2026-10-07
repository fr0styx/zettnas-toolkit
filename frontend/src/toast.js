/**
 * ZettNAS Toolkit Notification & Confirmation Toast System
 * Displays top-centered notifications below the top navbar (z-index 100000).
 */
import { ZettEventBus } from './event-bus.js';
import { state } from './state.js';
import { t } from './i18n.js';
import { escapeHtml } from './utils.js';

let _toastContainer = null;

function _getOrCreateToastContainer() {
  if (_toastContainer && document.body.contains(_toastContainer)) return _toastContainer;
  _toastContainer = document.getElementById("top-toast-container");
  if (!_toastContainer) {
    _toastContainer = document.createElement("div");
    _toastContainer.id = "top-toast-container";
    _toastContainer.setAttribute("role", "status");
    _toastContainer.setAttribute("aria-live", "polite");
    _toastContainer.setAttribute("aria-atomic", "false");
    document.body.appendChild(_toastContainer);
  }
  return _toastContainer;
}

export function showToast(msg, type = "error") {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
  _showTopNotification(msg, type);
  ZettEventBus.emit('toast:show', { msg, type });
}

export function showConfirmToast(title, msg, onConfirm, onCancel, options = {}) {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
  _showTopConfirm(title, msg, onConfirm, onCancel, options);
  ZettEventBus.emit('toast:confirm', { title, msg, onConfirm, onCancel, options });
}

export function hideConfirmToast() {
  const backdrop = document.getElementById("confirm-toast-backdrop");
  const card = document.getElementById("confirm-toast-modal");
  if (backdrop && card) {
    backdrop.style.opacity = "0";
    card.style.opacity = "0";
    card.style.pointerEvents = "none";
    card.style.transform = "translate(-50%, -15px) scale(0.95)";
    setTimeout(() => {
      backdrop.style.display = "none";
      card.style.display = "none";
    }, 200);
  }
}

// --- Multi-Toast Notification System (Top-centered stacked) ---
function _showTopNotification(msg, type = "error") {
  if (!document.body) return;
  const container = _getOrCreateToastContainer();

  // If container already has 3 or more active toasts, auto-dismiss oldest
  const existing = container.querySelectorAll('.top-toast-item');
  if (existing.length >= 3) {
    _dismissToastItem(existing[0]);
  }

  const toast = document.createElement("div");
  toast.className = "top-toast-item";

  const isErr = (type === "error" || type === "crit");
  const isWarn = (type === "warn" || type === "warning");
  const isSucc = (type === "success" || type === "ok");

  let borderColor = "#38bdf8";
  let icon = "ℹ️";
  let tagText = t('toast.info', "INFORMATION");
  let tagColor = "#38bdf8";

  if (isErr) {
    borderColor = "#ef4444";
    icon = "⚠️";
    tagText = t('toast.security_alert', "SECURITY / SYSTEM ALERT");
    tagColor = "#ef4444";
  } else if (isWarn) {
    borderColor = "#f59e0b";
    icon = "⚠️";
    tagText = t('toast.warning', "WARNING");
    tagColor = "#f59e0b";
  } else if (isSucc) {
    borderColor = "#22c55e";
    icon = "✅";
    tagText = t('toast.success', "SUCCESS");
    tagColor = "#22c55e";
  }

  toast.style.borderLeft = `4px solid ${borderColor}`;
  toast.innerHTML = `
    <div style="font-size: 20px; line-height: 1; flex-shrink: 0;">${icon}</div>
    <div style="flex: 1; min-width: 0;">
      <div style="font-size: 10px; font-weight: 800; letter-spacing: 0.8px; text-transform: uppercase; margin-bottom: 2px; color: ${tagColor};">${escapeHtml(tagText)}</div>
      <div style="font-size: 12.5px; color: #f1f5f9; line-height: 1.4; word-break: break-word;">${escapeHtml(msg)}</div>
    </div>
    <button class="top-toast-close" style="background: transparent; border: none; color: #94a3b8; font-size: 18px; cursor: pointer; padding: 2px 6px; line-height: 1; border-radius: 4px;" title="Dismiss">&times;</button>
  `;

  container.appendChild(toast);

  const closeBtn = toast.querySelector(".top-toast-close");
  if (closeBtn) {
    closeBtn.onmouseover = () => { closeBtn.style.color = "#fff"; closeBtn.style.background = "rgba(255,255,255,0.1)"; };
    closeBtn.onmouseout = () => { closeBtn.style.color = "#94a3b8"; closeBtn.style.background = "transparent"; };
    closeBtn.onclick = () => _dismissToastItem(toast);
  }

  requestAnimationFrame(() => {
    toast.classList.add("show");
  });

  const timer = setTimeout(() => {
    _dismissToastItem(toast);
  }, 6500);
  toast._dismissTimer = timer;
}

function _dismissToastItem(toast) {
  if (!toast || !toast.parentNode) return;
  if (toast._dismissTimer) clearTimeout(toast._dismissTimer);
  toast.classList.remove("show");
  setTimeout(() => {
    if (toast.parentNode) toast.parentNode.removeChild(toast);
  }, 260);
}

// --- Confirm Toast (Top-centered below navbar with backdrop) ---
function _showTopConfirm(title, msg, onConfirm, onCancel, options = {}) {
  if (!document.body) return;

  let backdrop = document.getElementById("confirm-toast-backdrop");
  if (!backdrop) {
    backdrop = document.createElement("div");
    backdrop.id = "confirm-toast-backdrop";
    document.body.appendChild(backdrop);
  }

  let card = document.getElementById("confirm-toast-modal");
  if (!card) {
    card = document.createElement("div");
    card.id = "confirm-toast-modal";
    document.body.appendChild(card);
  }
  if (!document.getElementById("confirm-toast-title")) {
    card.setAttribute("role", "alertdialog");
    card.setAttribute("aria-modal", "true");
    card.setAttribute("aria-labelledby", "confirm-toast-title");
    card.setAttribute("aria-describedby", "confirm-toast-msg");
    card.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; border-bottom: 1px solid rgba(255,255,255,0.08); background: rgba(14, 165, 233, 0.1);" id="confirm-toast-header-bg">
        <div style="display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; color: #0ea5e9;" id="confirm-toast-title">
          Confirm Action
        </div>
        <button id="confirm-toast-close" style="background: transparent; border: none; color: #94a3b8; font-size: 18px; cursor: pointer; padding: 2px 6px; line-height: 1; border-radius: 4px;" title="Cancel">&times;</button>
      </div>
      <div style="padding: 16px 20px;">
        <div id="confirm-toast-msg" style="font-size: 12.5px; color: #cbd5e1; line-height: 1.55; word-break: break-word;"></div>
        <div style="display: flex; gap: 10px; margin-top: 16px; justify-content: flex-end; align-items: center;">
          <button id="confirm-toast-eject" style="display: none; padding: 7px 14px; background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); border-radius: 6px; color: #f87171; font-size: 12px; font-weight: 600; cursor: pointer; margin-right: auto;" title="Safely unmount and eject card">⏏ Eject</button>
          <button id="confirm-toast-cancel" style="padding: 7px 16px; background: transparent; border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; color: #cbd5e1; font-size: 12px; font-weight: 600; cursor: pointer;">Cancel</button>
          <button id="confirm-toast-ok" style="padding: 7px 18px; background: #0ea5e9; border: 1px solid #0284c7; border-radius: 6px; color: #fff; font-size: 12px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px;">Confirm</button>
        </div>
      </div>
    `;
  }

  const titleEl = document.getElementById("confirm-toast-title");
  const msgEl = document.getElementById("confirm-toast-msg");
  const closeBtn = document.getElementById("confirm-toast-close");
  const cancelBtn = document.getElementById("confirm-toast-cancel");
  const okBtn = document.getElementById("confirm-toast-ok");
  const ejectBtn = document.getElementById("confirm-toast-eject");
  const headerBg = document.getElementById("confirm-toast-header-bg");

  const isStandby = title && title.toLowerCase().includes('standby');
  const isMedia = options.isMedia || (title && (title.toLowerCase().includes('media') || title.toLowerCase().includes('ingest') || title.toLowerCase().includes('card') || title.toLowerCase().includes('import')));

  if (isMedia) {
    titleEl.innerHTML = `<span>📷</span> ${title || "Media Card Ingest"}`;
    okBtn.innerHTML = options.okText || "📥 Import Media";
    okBtn.style.background = "linear-gradient(135deg, #0ea5e9, #25c2a0)";
    okBtn.style.border = "1px solid #0ea5e9";
    okBtn.style.color = "#fff";
    headerBg.style.background = "rgba(14, 165, 233, 0.12)";
    titleEl.style.color = "#38bdf8";
  } else if (isStandby) {
    titleEl.innerHTML = `<span>⚡</span> ${title || "Confirm Action"}`;
    okBtn.innerHTML = options.okText || "⚡ Wake & Inspect";
    okBtn.style.background = "#fbbf24";
    okBtn.style.border = "1px solid #f59e0b";
    okBtn.style.color = "#0a0e13";
    headerBg.style.background = "rgba(245, 158, 11, 0.08)";
    titleEl.style.color = "#fbbf24";
  } else {
    titleEl.innerHTML = `<span>💬</span> ${title || "Confirm Action"}`;
    okBtn.innerHTML = options.okText || "Confirm";
    okBtn.style.background = "#ef4444";
    okBtn.style.border = "1px solid #dc2626";
    okBtn.style.color = "#fff";
    headerBg.style.background = "rgba(239, 68, 68, 0.1)";
    titleEl.style.color = "#ef4444";
  }

  cancelBtn.innerHTML = options.cancelText || "Cancel";
  msgEl.innerHTML = msg || "";

  if (options.onEject && ejectBtn) {
    ejectBtn.style.display = "block";
    ejectBtn.innerHTML = options.ejectText || "⏏ Eject";
  } else if (ejectBtn) {
    ejectBtn.style.display = "none";
  }

  backdrop.style.display = "block";
  card.style.display = "block";
  card.style.pointerEvents = "auto";

  setTimeout(() => {
    backdrop.style.opacity = "1";
    card.style.opacity = "1";
    card.style.transform = "translate(-50%, 0) scale(1)";
  }, 10);

  const cleanup = () => {
    backdrop.style.opacity = "0";
    card.style.opacity = "0";
    card.style.pointerEvents = "none";
    card.style.transform = "translate(-50%, -15px) scale(0.95)";
    setTimeout(() => {
      backdrop.style.display = "none";
      card.style.display = "none";
    }, 200);
    closeBtn.removeEventListener("click", onCancelClick);
    cancelBtn.removeEventListener("click", onCancelClick);
    backdrop.removeEventListener("click", onCancelClick);
    okBtn.removeEventListener("click", onOkClick);
    if (ejectBtn) ejectBtn.removeEventListener("click", onEjectClick);
    document.removeEventListener("keydown", onKeyDown);
  };

  const onCancelClick = (e) => {
    if (e) e.preventDefault();
    cleanup();
    if (onCancel) onCancel();
  };
  const onOkClick = (e) => {
    if (e) e.preventDefault();
    cleanup();
    if (onConfirm) onConfirm();
  };
  const onEjectClick = (e) => {
    if (e) e.preventDefault();
    cleanup();
    if (options.onEject) options.onEject();
  };
  const onKeyDown = (e) => {
    if (e.key === "Escape") {
      onCancelClick(e);
    }
  };

  closeBtn.addEventListener("click", onCancelClick);
  cancelBtn.addEventListener("click", onCancelClick);
  backdrop.addEventListener("click", onCancelClick);
  okBtn.addEventListener("click", onOkClick);
  if (ejectBtn && options.onEject) ejectBtn.addEventListener("click", onEjectClick);
  document.addEventListener("keydown", onKeyDown);
}


export function showPromptToast(title, msg, defaultVal, onConfirm) {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
  if (!document.body) return;

  let backdrop = document.getElementById("confirm-toast-backdrop");
  if (!backdrop) {
    backdrop = document.createElement("div");
    backdrop.id = "confirm-toast-backdrop";
    document.body.appendChild(backdrop);
  }

  let card = document.getElementById("confirm-toast-modal");
  if (!card) {
    card = document.createElement("div");
    card.id = "confirm-toast-modal";
    document.body.appendChild(card);
  }

  card.innerHTML = `
    <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; border-bottom: 1px solid rgba(255,255,255,0.08); background: rgba(14, 165, 233, 0.1);">
      <div style="display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; color: #0ea5e9;">
        <span>✏️</span> ${title}
      </div>
      <button id="confirm-toast-close" style="background: transparent; border: none; color: #94a3b8; font-size: 18px; cursor: pointer; padding: 2px 6px; line-height: 1; border-radius: 4px;">&times;</button>
    </div>
    <div style="padding: 16px 20px;">
      <div style="font-size: 12.5px; color: #cbd5e1; margin-bottom: 12px;">${msg}</div>
      <input type="text" id="prompt-toast-input" style="width: 100%; background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); padding: 8px 12px; color: white; border-radius: 6px; font-size: 13px;" value="${defaultVal || ''}" />
      <div style="display: flex; gap: 10px; margin-top: 16px; justify-content: flex-end;">
        <button id="confirm-toast-cancel" style="padding: 7px 16px; background: transparent; border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; color: #cbd5e1; font-size: 12px; font-weight: 600; cursor: pointer;">Cancel</button>
        <button id="confirm-toast-ok" style="padding: 7px 18px; background: #0ea5e9; border: 1px solid #0284c7; border-radius: 6px; color: #fff; font-size: 12px; font-weight: 700; cursor: pointer;">Confirm</button>
      </div>
    </div>
  `;

  backdrop.style.display = "block";
  card.style.display = "block";
  card.style.pointerEvents = "auto";

  setTimeout(() => {
    backdrop.style.opacity = "1";
    card.style.opacity = "1";
    card.style.transform = "translate(-50%, 0) scale(1)";
    document.getElementById("prompt-toast-input").focus();
  }, 10);

  const cleanup = () => {
    backdrop.style.opacity = "0";
    card.style.opacity = "0";
    card.style.pointerEvents = "none";
    card.style.transform = "translate(-50%, -15px) scale(0.95)";
    setTimeout(() => {
      backdrop.style.display = "none";
      card.style.display = "none";
    }, 200);
  };

  document.getElementById("confirm-toast-close").onclick = cleanup;
  document.getElementById("confirm-toast-cancel").onclick = cleanup;
  document.getElementById("prompt-toast-input").onkeydown = (e) => {
    if (e.key === 'Enter') {
      cleanup();
      if (onConfirm) onConfirm(e.target.value);
    }
  };
  document.getElementById("confirm-toast-ok").onclick = () => {
    cleanup();
    if (onConfirm) onConfirm(document.getElementById("prompt-toast-input").value);
  };
}
