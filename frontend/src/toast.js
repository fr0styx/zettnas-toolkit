/**
 * ZettNAS Toolkit Notification & Confirmation Toast System
 * Displays top-centered notifications below the top navbar (z-index 100000).
 */
import { ZettEventBus } from './event-bus.js';
import { state } from './state.js';
import { t } from './i18n.js';
import { escapeHtml, sanitizeModalHtml } from './utils.js';
import { triggerHaptic } from './haptics.js';

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
  triggerHaptic(type === 'success' ? 'success' : type === 'warn' ? 'warning' : 'light');
  _showTopNotification(msg, type);
  ZettEventBus.emit('toast:show', { msg, type });
}

export function showActionToast(msg, actionText, onAction, durationMs = 10000) {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
  if (!document.body) return;
  triggerHaptic('light');
  const container = _getOrCreateToastContainer();

  const toast = document.createElement("div");
  toast.className = "top-toast-item";
  toast.style.borderLeft = `4px solid #38bdf8`;
  toast.innerHTML = `
    <div style="font-size: 20px; line-height: 1; flex-shrink: 0;">↺</div>
    <div style="flex: 1; min-width: 0;">
      <div style="font-size: 11px; font-weight: 800; letter-spacing: 0.8px; text-transform: uppercase; margin-bottom: 2px; color: #38bdf8;">NOTIFICATION</div>
      <div style="font-size: 12.5px; color: #f1f5f9; line-height: 1.4; word-break: break-word;">${escapeHtml(msg)}</div>
    </div>
    <button class="top-toast-action-btn" style="background: rgba(56, 189, 248, 0.2); border: 1px solid #38bdf8; color: #38bdf8; font-size: 11px; font-weight: 700; cursor: pointer; padding: 4px 10px; border-radius: 4px; margin-right: 6px;">${escapeHtml(actionText)}</button>
    <button class="top-toast-close" style="background: transparent; border: none; color: #94a3b8; font-size: 18px; cursor: pointer; padding: 2px 6px; line-height: 1; border-radius: 4px;" title="Dismiss">&times;</button>
  `;

  container.appendChild(toast);

  const actionBtn = toast.querySelector(".top-toast-action-btn");
  if (actionBtn) {
    actionBtn.onclick = () => {
      _dismissToastItem(toast);
      if (typeof onAction === 'function') onAction();
    };
  }

  const closeBtn = toast.querySelector(".top-toast-close");
  if (closeBtn) {
    closeBtn.onclick = () => _dismissToastItem(toast);
  }

  requestAnimationFrame(() => {
    toast.classList.add("show");
  });

  const timer = setTimeout(() => {
    _dismissToastItem(toast);
  }, durationMs);
  toast._dismissTimer = timer;
}

// A dialog that was dragged opens in its usual place next time
function resetDraggedPosition(el) {
  for (const prop of ["position", "left", "top", "right", "bottom", "margin", "transition"]) el.style.removeProperty(prop);
}

export function showConfirmToast(title, msg, onConfirm, onCancel, options = {}) {
  if (typeof msg === 'function') {
    options = onCancel || {};
    onCancel = onConfirm || null;
    onConfirm = msg;
    msg = title;
    title = options.title || 'Confirm Action';
  }
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
  triggerHaptic('warning');
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
      <div style="font-size: 11px; font-weight: 800; letter-spacing: 0.8px; text-transform: uppercase; margin-bottom: 2px; color: ${tagColor};">${escapeHtml(tagText)}</div>
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
  if (typeof msg === 'function') {
    options = onCancel || {};
    onCancel = onConfirm || null;
    onConfirm = msg;
    msg = title;
    title = options.title || 'Confirm Action';
  }
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
    card.dataset.dialogChrome = "alert"; // standard title bar and close button (dialog-chrome.js)
    document.body.appendChild(card);
  }
  if (card.dataset.mode !== "confirm") {
    card.dataset.mode = "confirm";
    card.setAttribute("role", "alertdialog");
    card.setAttribute("aria-modal", "true");
    card.setAttribute("aria-labelledby", "confirm-toast-title");
    card.setAttribute("aria-describedby", "confirm-toast-msg");
    card.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; border-bottom: 1px solid rgba(255,255,255,0.08); background: rgba(14, 165, 233, 0.1);" id="confirm-toast-header-bg" data-dialog-header>
        <div style="display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; color: #0ea5e9;" id="confirm-toast-title">
          Confirm Action
        </div>
        <button type="button" id="confirm-toast-close" class="win-btn close-btn" title="Cancel" aria-label="Close"></button>
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
  const isUpdate = options.isUpdate || (title && (title.toLowerCase().includes('update') || title.toLowerCase().includes('upgrade')));

  const safeTitle = escapeHtml(title || "Confirm Action");
  let safeMsg;
  if (options.allowHtml === false) {
    safeMsg = escapeHtml(msg || "");
  } else if (options.allowHtml || (msg && /<[a-z0-9]+/i.test(msg))) {
    safeMsg = sanitizeModalHtml(msg || "");
  } else {
    safeMsg = escapeHtml(msg || "");
  }

  if (isMedia) {
    titleEl.innerHTML = `<span>📷</span> ${safeTitle}`;
    okBtn.innerHTML = options.okText ? escapeHtml(options.okText) : "📥 Import Media";
    okBtn.style.background = "linear-gradient(135deg, #0ea5e9, #25c2a0)";
    okBtn.style.border = "1px solid #0ea5e9";
    okBtn.style.color = "#fff";
    headerBg.style.background = "rgba(14, 165, 233, 0.12)";
    titleEl.style.color = "#38bdf8";
  } else if (isStandby) {
    titleEl.innerHTML = `<span>⚡</span> ${safeTitle}`;
    okBtn.innerHTML = options.okText ? escapeHtml(options.okText) : "⚡ Wake & Inspect";
    okBtn.style.background = "#fbbf24";
    okBtn.style.border = "1px solid #f59e0b";
    okBtn.style.color = "#0a0e13";
    headerBg.style.background = "rgba(245, 158, 11, 0.08)";
    titleEl.style.color = "#fbbf24";
  } else if (isUpdate) {
    titleEl.innerHTML = `<span>⬆️</span> ${safeTitle}`;
    okBtn.innerHTML = options.okText ? escapeHtml(options.okText) : "⬆️ Update Now";
    okBtn.style.background = "linear-gradient(135deg, #f59e0b, #d97706)";
    okBtn.style.border = "1px solid #f59e0b";
    okBtn.style.color = "#0a0e13";
    okBtn.style.fontWeight = "700";
    headerBg.style.background = "rgba(245, 158, 11, 0.14)";
    titleEl.style.color = "#fbbf24";
  } else {
    const isDelete = options.icon === '🗑️' || (title && (title.toLowerCase().includes('delete') || title.toLowerCase().includes('remove') || title.toLowerCase().includes('destroy')));
    const icon = options.icon || (isDelete ? '🗑️' : '💬');
    titleEl.innerHTML = `<span>${icon}</span> ${safeTitle}`;
    okBtn.innerHTML = options.okText ? escapeHtml(options.okText) : "Confirm";
    okBtn.style.background = "#ef4444";
    okBtn.style.border = "1px solid #dc2626";
    okBtn.style.color = "#fff";
    headerBg.style.background = "rgba(239, 68, 68, 0.1)";
    titleEl.style.color = "#ef4444";
    card.style.borderColor = "rgba(239, 68, 68, 0.45)";
    card.style.boxShadow = "0 24px 60px rgba(0, 0, 0, 0.9), 0 0 30px rgba(239, 68, 68, 0.15)";
  }

  cancelBtn.innerHTML = options.cancelText ? escapeHtml(options.cancelText) : "Cancel";
  msgEl.innerHTML = safeMsg;

  if (options.onEject && ejectBtn) {
    ejectBtn.style.display = "block";
    ejectBtn.innerHTML = options.ejectText || "⏏ Eject";
  } else if (ejectBtn) {
    ejectBtn.style.display = "none";
  }

  resetDraggedPosition(card);
  backdrop.style.display = "block";
  card.style.display = "block";
  card.style.pointerEvents = "auto";

  setTimeout(() => {
    backdrop.classList.add("open");
    card.classList.add("open");
    backdrop.style.opacity = "1";
    card.style.opacity = "1";
    card.style.transform = "translate(-50%, 0) scale(1)";
  }, 10);

  const cleanup = () => {
    backdrop.classList.remove("open");
    card.classList.remove("open");
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


export function showPromptToast(title, msg, defaultVal, onConfirm, onCancel = null, options = {}) {
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
    card.dataset.dialogChrome = "alert"; // standard title bar and close button (dialog-chrome.js)
    document.body.appendChild(card);
  }

  card.dataset.mode = "prompt";
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-modal", "true");
  card.setAttribute("aria-labelledby", "confirm-toast-title");

  const inputType = options.inputType || "text";
  const okText = options.okText || "Confirm";
  const cancelText = options.cancelText || "Cancel";
  const icon = options.icon || "✏️";
  const placeholder = options.placeholder || "";

  const isTextarea = inputType === "textarea";
  const inputHtml = isTextarea
    ? `<textarea id="prompt-toast-input" placeholder="${escapeHtml(placeholder)}" style="width: 100%; box-sizing: border-box; background: rgba(0,0,0,0.6); border: 1px solid rgba(0, 240, 255, 0.4); padding: 9px 12px; color: white; border-radius: 6px; font-size: 13px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; outline: none; min-height: 96px; resize: vertical; line-height: 1.45;">${escapeHtml(defaultVal || '')}</textarea>`
    : `<input type="${inputType}" id="prompt-toast-input" placeholder="${escapeHtml(placeholder)}" style="width: 100%; box-sizing: border-box; background: rgba(0,0,0,0.6); border: 1px solid rgba(0, 240, 255, 0.4); padding: 9px 12px; color: white; border-radius: 6px; font-size: 13px; outline: none;" value="${escapeHtml(defaultVal || '')}" />`;

  const safePromptMsg = options.allowHtml === false
    ? escapeHtml(msg || "")
    : (options.allowHtml || (msg && /<[a-z0-9]+/i.test(msg)))
      ? sanitizeModalHtml(msg || "")
      : escapeHtml(msg || "");

  card.innerHTML = `
    <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; border-bottom: 1px solid rgba(255,255,255,0.08); background: rgba(0, 240, 255, 0.08);" id="confirm-toast-header-bg" data-dialog-header>
      <div style="display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; color: var(--brand, #00f0ff);" id="confirm-toast-title">
        <span>${icon}</span> ${escapeHtml(title || "Rename")}
      </div>
      <button type="button" id="confirm-toast-close" class="win-btn close-btn" title="Cancel" aria-label="Close"></button>
    </div>
    <div style="padding: 16px 20px;">
      <div style="font-size: 12.5px; color: #cbd5e1; margin-bottom: 12px; line-height: 1.5;">${safePromptMsg}</div>
      ${inputHtml}
      <div style="display: flex; gap: 10px; margin-top: 16px; justify-content: flex-end; align-items: center;">
        <button id="confirm-toast-cancel" style="padding: 7px 16px; background: transparent; border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; color: #cbd5e1; font-size: 12px; font-weight: 600; cursor: pointer;">${escapeHtml(cancelText)}</button>
        <button id="confirm-toast-ok" style="padding: 7px 18px; background: var(--brand, #00f0ff); border: 1px solid var(--brand, #00f0ff); border-radius: 6px; color: #050b14; font-size: 12px; font-weight: 700; cursor: pointer;">${escapeHtml(okText)}</button>
      </div>
    </div>
  `;

  resetDraggedPosition(card);
  backdrop.style.display = "block";
  card.style.display = "flex";
  card.style.pointerEvents = "auto";

  setTimeout(() => {
    backdrop.classList.add("open");
    card.classList.add("open");
    backdrop.style.opacity = "1";
    card.style.opacity = "1";
    card.style.transform = "translate(-50%, 0) scale(1)";
    const input = document.getElementById("prompt-toast-input");
    if (input) {
      input.focus();
      input.select();
    }
  }, 10);

  const cleanup = () => {
    backdrop.classList.remove("open");
    card.classList.remove("open");
    backdrop.style.opacity = "0";
    card.style.opacity = "0";
    card.style.pointerEvents = "none";
    card.style.transform = "translate(-50%, -15px) scale(0.95)";
    setTimeout(() => {
      backdrop.style.display = "none";
      card.style.display = "none";
    }, 200);
    document.removeEventListener("keydown", onKeyDown);
  };

  const onCancelClick = (e) => {
    if (e) e.preventDefault();
    cleanup();
    if (onCancel) onCancel();
  };

  const onOkClick = (e) => {
    if (e) e.preventDefault();
    const input = document.getElementById("prompt-toast-input");
    const val = input ? input.value : "";
    cleanup();
    if (onConfirm) onConfirm(val);
  };

  const onKeyDown = (e) => {
    if (e.key === "Escape") {
      onCancelClick(e);
    }
  };

  document.getElementById("confirm-toast-close").onclick = onCancelClick;
  document.getElementById("confirm-toast-cancel").onclick = onCancelClick;
  backdrop.onclick = onCancelClick;
  document.getElementById("confirm-toast-ok").onclick = onOkClick;
  const inputEl = document.getElementById("prompt-toast-input");
  if (inputEl) {
    inputEl.onkeydown = (e) => {
      if (isTextarea) {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
          e.preventDefault();
          onOkClick(e);
        }
      } else {
        if (e.key === "Enter") {
          e.preventDefault();
          onOkClick(e);
        }
      }
    };
  }
  document.addEventListener("keydown", onKeyDown);
}

export function showBottomSheet({ title, subtitle, items = [], onCancel = null }) {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
  if (!document.body) return;

  let backdrop = document.getElementById("mobile-sheet-backdrop");
  if (!backdrop) {
    backdrop = document.createElement("div");
    backdrop.id = "mobile-sheet-backdrop";
    backdrop.className = "mobile-sheet-backdrop";
    document.body.appendChild(backdrop);
  }

  let sheet = document.getElementById("mobile-bottom-sheet");
  if (!sheet) {
    sheet = document.createElement("div");
    sheet.id = "mobile-bottom-sheet";
    sheet.className = "mobile-bottom-sheet";
    document.body.appendChild(sheet);
  }

  const itemsHtml = items.map((item, idx) => `
    <button type="button" class="sheet-action-item ${item.destructive ? 'destructive' : ''}" data-index="${idx}">
      <span class="sheet-action-icon">${item.icon || '•'}</span>
      <span class="sheet-action-label">${escapeHtml(item.label || '')}</span>
      <span class="sheet-action-arrow">›</span>
    </button>
  `).join('');

  sheet.innerHTML = `
    <div class="sheet-handle-bar">
      <div class="sheet-drag-handle"></div>
    </div>
    <div class="sheet-header">
      <div class="sheet-title">${escapeHtml(title || 'Actions')}</div>
      ${subtitle ? `<div class="sheet-subtitle">${escapeHtml(subtitle)}</div>` : ''}
    </div>
    <div class="sheet-content">
      ${itemsHtml}
    </div>
    <div class="sheet-footer">
      <button type="button" class="sheet-cancel-btn" id="sheet-cancel-btn">${escapeHtml(t('common.cancel', 'Cancel'))}</button>
    </div>
  `;

  backdrop.style.display = "block";
  sheet.style.display = "flex";
  sheet.style.transform = "";
  sheet.style.transition = "";

  requestAnimationFrame(() => {
    backdrop.classList.add("open");
    sheet.classList.add("open");
  });

  const cleanup = () => {
    backdrop.classList.remove("open");
    sheet.classList.remove("open");
    sheet.style.transform = "";
    sheet.style.transition = "";
    setTimeout(() => {
      backdrop.style.display = "none";
      sheet.style.display = "none";
    }, 250);
    document.removeEventListener("keydown", onKeyDown);
  };

  const onCancelClick = () => {
    cleanup();
    if (onCancel) onCancel();
  };

  const onKeyDown = (e) => {
    if (e.key === "Escape") onCancelClick();
  };

  // Swipe-down-to-dismiss gesture on handle bar & header
  const handleBar = sheet.querySelector(".sheet-handle-bar");
  const headerBar = sheet.querySelector(".sheet-header");
  let startY = 0;
  let currentDy = 0;
  let isDragging = false;

  const onPointerDown = (e) => {
    if (e.button !== undefined && e.button !== 0) return;
    isDragging = true;
    startY = e.clientY || (e.touches && e.touches[0] ? e.touches[0].clientY : 0);
    currentDy = 0;
    sheet.style.transition = "none";
    if (e.currentTarget && typeof e.currentTarget.setPointerCapture === "function" && e.pointerId !== undefined) {
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) {}
    }
  };

  const onPointerMove = (e) => {
    if (!isDragging) return;
    const clientY = e.clientY !== undefined ? e.clientY : (e.touches && e.touches[0] ? e.touches[0].clientY : startY);
    currentDy = Math.max(0, clientY - startY);
    sheet.style.transform = `translateY(${currentDy}px)`;
  };

  const onPointerEnd = (e) => {
    if (!isDragging) return;
    isDragging = false;
    sheet.style.transition = "";
    if (e.type !== "pointercancel" && currentDy > 70) {
      sheet.style.transform = "";
      onCancelClick();
    } else {
      sheet.style.transform = "";
    }
  };

  [handleBar, headerBar].forEach((el) => {
    if (!el) return;
    el.addEventListener("pointerdown", onPointerDown);
    el.addEventListener("pointermove", onPointerMove);
    el.addEventListener("pointerup", onPointerEnd);
    el.addEventListener("pointercancel", onPointerEnd);
  });

  backdrop.onclick = onCancelClick;
  const cancelBtn = sheet.querySelector("#sheet-cancel-btn");
  if (cancelBtn) cancelBtn.onclick = onCancelClick;

  sheet.querySelectorAll(".sheet-action-item").forEach((btn) => {
    btn.onclick = () => {
      const idx = parseInt(btn.dataset.index, 10);
      const item = items[idx];
      cleanup();
      if (item && typeof item.onClick === "function") {
        item.onClick();
      }
    };
  });

  document.addEventListener("keydown", onKeyDown);
}

