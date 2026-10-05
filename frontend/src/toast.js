/**
 * ZettNAS Toolkit Notification & Confirmation Toast System
 * Displays top-centered notifications below the top navbar (z-index 100000).
 */
import { ZettEventBus } from './event-bus.js';
import { state } from './state.js';

let _toastTimeout = null;

export function showToast(msg, type = "error") {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
  _showTopNotification(msg, type);
  ZettEventBus.emit('toast:show', { msg, type });
}

export function showConfirmToast(title, msg, onConfirm) {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
  _showTopConfirm(title, msg, onConfirm);
  ZettEventBus.emit('toast:confirm', { title, msg, onConfirm });
}

window.showToast = showToast;
window.showConfirmToast = showConfirmToast;

// --- Notification Toast (Top-centered below navbar) ---
function _showTopNotification(msg, type = "error") {
  if (!document.body) return;

  let toast = document.getElementById("top-notification-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "top-notification-toast";
    toast.innerHTML = `
      <div id="top-toast-icon" style="font-size: 20px; line-height: 1; flex-shrink: 0;"></div>
      <div style="flex: 1; min-width: 0;">
        <div id="top-toast-tag" style="font-size: 10px; font-weight: 800; letter-spacing: 0.8px; text-transform: uppercase; margin-bottom: 2px;"></div>
        <div id="top-toast-msg" style="font-size: 12.5px; color: #f1f5f9; line-height: 1.4; word-break: break-word;"></div>
      </div>
      <button id="top-toast-close" style="background: transparent; border: none; color: #94a3b8; font-size: 18px; cursor: pointer; padding: 2px 6px; line-height: 1; border-radius: 4px;" title="Dismiss">&times;</button>
    `;
    document.body.appendChild(toast);

    const closeBtn = document.getElementById("top-toast-close");
    if (closeBtn) {
      closeBtn.onmouseover = () => { closeBtn.style.color = "#fff"; closeBtn.style.background = "rgba(255,255,255,0.1)"; };
      closeBtn.onmouseout = () => { closeBtn.style.color = "#94a3b8"; closeBtn.style.background = "transparent"; };
      closeBtn.onclick = () => _dismissTopNotification();
    }
  }

  const iconEl = document.getElementById("top-toast-icon");
  const tagEl = document.getElementById("top-toast-tag");
  const msgEl = document.getElementById("top-toast-msg");

  const isErr = (type === "error" || type === "crit");
  const isWarn = (type === "warn" || type === "warning");
  const isSucc = (type === "success" || type === "ok");

  if (isErr) {
    toast.style.borderLeft = "4px solid #ef4444";
    if (iconEl) iconEl.textContent = "⚠️";
    if (tagEl) { tagEl.textContent = "SECURITY / SYSTEM ALERT"; tagEl.style.color = "#ef4444"; }
  } else if (isWarn) {
    toast.style.borderLeft = "4px solid #f59e0b";
    if (iconEl) iconEl.textContent = "⚠️";
    if (tagEl) { tagEl.textContent = "WARNING"; tagEl.style.color = "#f59e0b"; }
  } else if (isSucc) {
    toast.style.borderLeft = "4px solid #22c55e";
    if (iconEl) iconEl.textContent = "✅";
    if (tagEl) { tagEl.textContent = "SUCCESS"; tagEl.style.color = "#22c55e"; }
  } else {
    toast.style.borderLeft = "4px solid #38bdf8";
    if (iconEl) iconEl.textContent = "ℹ️";
    if (tagEl) { tagEl.textContent = "INFORMATION"; tagEl.style.color = "#38bdf8"; }
  }

  if (msgEl) msgEl.textContent = msg;

  if (_toastTimeout) clearTimeout(_toastTimeout);

  toast.classList.add("show");

  _toastTimeout = setTimeout(() => {
    _dismissTopNotification();
  }, 6500);
}

function _dismissTopNotification() {
  const toast = document.getElementById("top-notification-toast");
  if (!toast) return;
  toast.classList.remove("show");
}

// --- Confirm Toast (Top-centered below navbar with backdrop) ---
function _showTopConfirm(title, msg, onConfirm) {
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
    card.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; border-bottom: 1px solid rgba(255,255,255,0.08); background: rgba(245, 158, 11, 0.08);">
        <div style="display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; color: #fbbf24;" id="confirm-toast-title">
          <span>💤</span> Drive in Standby Mode
        </div>
        <button id="confirm-toast-close" style="background: transparent; border: none; color: #94a3b8; font-size: 18px; cursor: pointer; padding: 2px 6px; line-height: 1; border-radius: 4px;" title="Cancel">&times;</button>
      </div>
      <div style="padding: 16px 20px;">
        <div id="confirm-toast-msg" style="font-size: 12.5px; color: #cbd5e1; line-height: 1.55; word-break: break-word;"></div>
        <div style="display: flex; gap: 10px; margin-top: 16px; justify-content: flex-end;">
          <button id="confirm-toast-cancel" style="padding: 7px 16px; background: transparent; border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; color: #cbd5e1; font-size: 12px; font-weight: 600; cursor: pointer;">Cancel</button>
          <button id="confirm-toast-ok" style="padding: 7px 18px; background: #fbbf24; border: 1px solid #f59e0b; border-radius: 6px; color: #0a0e13; font-size: 12px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px;">⚡ Wake & Inspect</button>
        </div>
      </div>
    `;
    document.body.appendChild(card);
  }

  const titleEl = document.getElementById("confirm-toast-title");
  const msgEl = document.getElementById("confirm-toast-msg");
  const closeBtn = document.getElementById("confirm-toast-close");
  const cancelBtn = document.getElementById("confirm-toast-cancel");
  const okBtn = document.getElementById("confirm-toast-ok");

  if (titleEl) {
    titleEl.innerHTML = `<span>💤</span> ${title || "Confirm Action"}`;
  }
  if (msgEl) {
    msgEl.textContent = msg || "Are you sure you want to proceed?";
  }

  const close = () => {
    backdrop.classList.remove("open");
    card.classList.remove("open");
  };

  closeBtn.onclick = close;
  cancelBtn.onclick = close;
  backdrop.onclick = close;

  okBtn.onclick = () => {
    close();
    if (typeof onConfirm === "function") {
      onConfirm();
    }
  };

  // Open confirm card
  backdrop.classList.add("open");
  card.classList.add("open");
}

// Global EventBus listeners registered immediately (no DOMContentLoaded dependency)
ZettEventBus.on('toast:show', (detail) => {
  if (detail && detail.msg) _showTopNotification(detail.msg, detail.type);
});
ZettEventBus.on('toast:confirm', (detail) => {
  if (detail) _showTopConfirm(detail.title, detail.msg, detail.onConfirm);
});
