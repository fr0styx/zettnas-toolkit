/**
 * ZettNAS Toolkit Notification & Confirmation Toast System
 * Displays top-centered notifications below the top navbar (z-index 100000).
 */
import { ZettEventBus } from './event-bus.js';
import { state } from './state.js';
import { t } from './i18n.js';
import { detailsFor } from './error-text.js';
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
      <div style="font-size: var(--zn-fs-xs); font-weight: 800; letter-spacing: 0.8px; text-transform: uppercase; margin-bottom: 2px; color: var(--zn-text-accent);">NOTIFICATION</div>
      <div style="font-size: var(--zn-fs-xs); color: var(--zn-text-bright); line-height: 1.4; word-break: break-word;">${escapeHtml(msg)}</div>
    </div>
    <button class="top-toast-action-btn" style="background: rgba(56, 189, 248, 0.2); border: 1px solid #38bdf8; color: var(--zn-text-accent); font-size: var(--zn-fs-xs); font-weight: 700; cursor: pointer; padding: 4px 10px; border-radius: 4px; margin-right: 6px;"${UNDO_RE.test(actionText) ? ' aria-keyshortcuts="Control+Z Meta+Z"' : ''}>${escapeHtml(actionText)}</button>
    <button class="top-toast-close" style="background: transparent; border: none; color: var(--zn-text-muted); font-size: 18px; cursor: pointer; padding: 2px 6px; line-height: 1; border-radius: 4px;" title="${escapeHtml(t('toast.dismiss', 'Dismiss'))}" aria-label="${escapeHtml(t('toast.dismiss', 'Dismiss'))}">&times;</button>
  `;

  if (UNDO_RE.test(actionText)) toast.dataset.undo = '1';
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

  _armDismiss(toast, durationMs);
}

// Words that mark an action as destructive (the button turns red), in the five UI languages
const DESTRUCTIVE_RE = /\b(delete|remove|destroy|wipe|format|erase|revoke|reset|clear|uninstall|purge|discard|kill|löschen|entfernen|zurücksetzen|supprimer|effacer|retirer|eliminar|borrar|quitar)\b|删除|移除|清除|清空/i;
const GENERIC_TITLES = new Set(['confirm action', 'confirm', 'are you sure?']);

/** The button label and colour for a confirm dialog (UX-5: verbs, red only when destructive). */
export function confirmButtonFor(title, msg, options = {}) {
  const text = `${title || ''} ${options.okText || ''}`;
  const destructive = options.destructive ?? (DESTRUCTIVE_RE.test(text) || (GENERIC_TITLES.has(String(title || '').trim().toLowerCase()) && DESTRUCTIVE_RE.test(String(msg || '').slice(0, 60))));
  let label = options.okText;
  if (!label) {
    const plain = String(title || '').trim();
    if (plain && !GENERIC_TITLES.has(plain.toLowerCase()) && plain.length <= 28) label = plain.replace(/[?.!…]+$/, '');
    else label = t('confirm.continue', 'Continue');
  }
  return { label, destructive };
}

function _focusables(card) {
  return [...card.querySelectorAll('button, input, textarea, select, [tabindex]:not([tabindex="-1"])')]
    .filter((el) => !el.disabled && el.style.display !== 'none' && !el.closest('[hidden]'));
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

  const isSecurity = type === "security";
  const isErr = (type === "error" || type === "crit" || isSecurity);
  const isWarn = (type === "warn" || type === "warning");
  const isSucc = (type === "success" || type === "ok");

  let borderColor = "#38bdf8";
  let icon = "ℹ️";
  let tagText = t('toast.info', "Information");
  let tagColor = "#38bdf8";

  if (isErr) {
    borderColor = "#ef4444";
    icon = "⚠️";
    // Security wording only for security events; an ordinary failure is just an error.
    tagText = isSecurity ? t('toast.security_alert', "Security alert") : t('toast.error_heading', "Error");
    tagColor = "#ef4444";
  } else if (isWarn) {
    borderColor = "#f59e0b";
    icon = "⚠️";
    tagText = t('toast.warning', "Warning");
    tagColor = "#f59e0b";
  } else if (isSucc) {
    borderColor = "#22c55e";
    icon = "✅";
    tagText = t('toast.success', "Done");
    tagColor = "#22c55e";
  }

  toast.style.borderLeft = `4px solid ${borderColor}`;
  if (isErr) toast.setAttribute("role", "alert");
  // UX-22: a translated error keeps the server's own words under "Details"
  const details = isErr ? detailsFor(msg) : '';
  toast.innerHTML = `
    <div style="font-size: 20px; line-height: 1; flex-shrink: 0;">${icon}</div>
    <div style="flex: 1; min-width: 0;">
      <div style="font-size: var(--zn-fs-xs); font-weight: 800; letter-spacing: 0.8px; text-transform: uppercase; margin-bottom: 2px; color: ${tagColor};">${escapeHtml(tagText)}</div>
      <div style="font-size: var(--zn-fs-xs); color: var(--zn-text-bright); line-height: 1.4; word-break: break-word;">${escapeHtml(msg)}</div>
      ${details ? `<details class="top-toast-details"><summary>${escapeHtml(t('toast.details', 'Details'))}</summary><div class="top-toast-details-text">${escapeHtml(details)}</div></details>` : ''}
    </div>
    <button class="top-toast-close" style="background: transparent; border: none; color: var(--zn-text-muted); font-size: 18px; cursor: pointer; padding: 2px 6px; line-height: 1; border-radius: 4px;" title="${escapeHtml(t('toast.dismiss', 'Dismiss'))}" aria-label="${escapeHtml(t('toast.dismiss', 'Dismiss'))}">&times;</button>
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

  // UX-27: an error stays until it is closed; anything else goes after a while, but not while
  // the pointer or the keyboard is on it
  if (!isErr) _armDismiss(toast, TOAST_MS);
}

export const TOAST_MS = 6500;

/** Dismisses the toast after ms, paused while it is hovered or focused (UX-27). */
function _armDismiss(toast, ms) {
  toast._remaining = ms;
  const start = () => {
    if (toast._dismissTimer || !toast.isConnected) return;
    toast._startedAt = Date.now();
    toast._dismissTimer = setTimeout(() => _dismissToastItem(toast), toast._remaining);
  };
  const pause = () => {
    if (!toast._dismissTimer) return;
    clearTimeout(toast._dismissTimer);
    toast._dismissTimer = null;
    toast._remaining = Math.max(1500, toast._remaining - (Date.now() - toast._startedAt));
  };
  toast.addEventListener('mouseenter', pause);
  toast.addEventListener('focusin', pause);
  toast.addEventListener('mouseleave', () => { if (!toast.contains(document.activeElement)) start(); });
  toast.addEventListener('focusout', (e) => { if (!toast.contains(e.relatedTarget) && !toast.matches(':hover')) start(); });
  start();
}

// UX-27: Ctrl/Cmd+Z takes the newest Undo offer (outside text fields, where it undoes typing)
const UNDO_RE = /undo|rückgängig|deshacer|annuler|撤销|↺/i;

function _onUndoKey(e) {
  if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey || String(e.key).toLowerCase() !== 'z') return;
  const el = document.activeElement;
  if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
  const offers = document.querySelectorAll('#top-toast-container .top-toast-item[data-undo] .top-toast-action-btn');
  const newest = offers[offers.length - 1];
  if (!newest) return;
  e.preventDefault();
  newest.click();
}

if (typeof document !== 'undefined' && !document._znUndoKey) {
  document._znUndoKey = true;
  document.addEventListener('keydown', _onUndoKey);
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
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; border-bottom: 1px solid var(--zn-line-8); background: rgba(14, 165, 233, 0.1);" id="confirm-toast-header-bg" data-dialog-header>
        <div style="display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; color: var(--lt-t-0ea5e9ff, #0ea5e9);" id="confirm-toast-title">
          Confirm Action
        </div>
        <button type="button" id="confirm-toast-close" class="win-btn close-btn" title="${t('jobs.cancel', 'Cancel')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
      </div>
      <div style="padding: 16px 20px;">
        <div id="confirm-toast-msg" style="font-size: var(--zn-fs-xs); color: var(--zn-text-soft); line-height: 1.55; word-break: break-word;"></div>
        <div style="display: flex; gap: 10px; margin-top: 16px; justify-content: flex-end; align-items: center;">
          <button id="confirm-toast-eject" class="btn-pill-toggle is-danger is-small" style="display: none; margin-right: auto;" title="${t('ui.safely_unmount_and_eject_card', 'Safely unmount and eject card')}">⏏ Eject</button>
          <button id="confirm-toast-cancel" class="btn-pill-toggle is-small">Cancel</button>
          <button id="confirm-toast-ok" style="padding: 7px 18px; background: #0ea5e9; border: 1px solid #0284c7; border-radius: 6px; color: #fff; font-size: var(--zn-fs-xs); font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px;">Confirm</button>
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
    titleEl.innerHTML = `<span aria-hidden="true">📷</span> ${safeTitle}`;
    okBtn.innerHTML = options.okText ? escapeHtml(options.okText) : "📥 Import Media";
    okBtn.style.background = "linear-gradient(135deg, #0ea5e9, #25c2a0)";
    okBtn.style.border = "1px solid #0ea5e9";
    okBtn.style.color = "#fff";
    headerBg.style.background = "rgba(14, 165, 233, 0.12)";
    titleEl.style.color = "#38bdf8";
  } else if (isStandby) {
    titleEl.innerHTML = `<span aria-hidden="true">⚡</span> ${safeTitle}`;
    okBtn.innerHTML = options.okText ? escapeHtml(options.okText) : "⚡ Wake & Inspect";
    okBtn.style.background = "#fbbf24";
    okBtn.style.border = "1px solid #f59e0b";
    okBtn.style.color = "#0a0e13";
    headerBg.style.background = "rgba(245, 158, 11, 0.08)";
    titleEl.style.color = "#fbbf24";
  } else if (isUpdate) {
    titleEl.innerHTML = `<span aria-hidden="true">⬆️</span> ${safeTitle}`;
    okBtn.innerHTML = options.okText ? escapeHtml(options.okText) : "⬆️ Update Now";
    okBtn.style.background = "linear-gradient(135deg, #f59e0b, #d97706)";
    okBtn.style.border = "1px solid #f59e0b";
    okBtn.style.color = "#0a0e13";
    okBtn.style.fontWeight = "700";
    headerBg.style.background = "rgba(245, 158, 11, 0.14)";
    titleEl.style.color = "#fbbf24";
  } else {
    const { label, destructive } = confirmButtonFor(title, msg, options);
    card.dataset.destructive = destructive ? "true" : "false";
    const icon = options.icon || (destructive ? '🗑️' : '💬');
    titleEl.innerHTML = `<span aria-hidden="true">${icon}</span> ${safeTitle}`;
    okBtn.innerHTML = escapeHtml(label);
    if (destructive) {
      okBtn.style.background = "#ef4444";
      okBtn.style.border = "1px solid #dc2626";
      headerBg.style.background = "rgba(239, 68, 68, 0.1)";
      titleEl.style.color = "#ef4444";
      card.style.borderColor = "rgba(239, 68, 68, 0.45)";
      card.style.boxShadow = "0 24px 60px rgba(0, 0, 0, 0.9), 0 0 30px rgba(239, 68, 68, 0.15)";
    } else {
      okBtn.style.background = "#0ea5e9";
      okBtn.style.border = "1px solid #0284c7";
      headerBg.style.background = "rgba(14, 165, 233, 0.1)";
      titleEl.style.color = "#0ea5e9";
      card.style.borderColor = "";
      card.style.boxShadow = "";
    }
    okBtn.style.color = "#fff";
  }

  cancelBtn.innerHTML = options.cancelText ? escapeHtml(options.cancelText) : escapeHtml(t('confirm.cancel', 'Cancel'));
  msgEl.innerHTML = safeMsg;

  // UX-6: big deletes ask to type the name first
  card.querySelector('#confirm-toast-type')?.remove();
  let typeInput = null;
  okBtn.disabled = false;
  okBtn.style.opacity = "";
  if (options.typeToConfirm) {
    const expected = String(options.typeToConfirm);
    const wrap = document.createElement('div');
    wrap.id = 'confirm-toast-type';
    wrap.style.marginTop = '12px';
    wrap.innerHTML = `<label for="confirm-toast-type-input" style="display:block; font-size: var(--zn-fs-xs); color: var(--zn-text-soft); margin-bottom: 6px;"></label>
      <input id="confirm-toast-type-input" type="text" autocomplete="off" spellcheck="false" style="width: 100%; box-sizing: border-box; background: var(--lt-b-00000099, rgba(0,0,0,0.6)); border: 1px solid var(--zn-line-15); padding: 8px 10px; color: var(--zn-text-strong); border-radius: 6px; font-size: 13px; outline: none;" />`;
    wrap.querySelector('label').textContent = t('confirm.type_to_confirm', 'Type {name} to confirm', { name: expected });
    msgEl.after(wrap);
    typeInput = wrap.querySelector('input');
    const sync = () => {
      const ok = typeInput.value.trim() === expected;
      okBtn.disabled = !ok;
      okBtn.style.opacity = ok ? "" : "0.45";
    };
    typeInput.addEventListener('input', sync);
    sync();
  }
  const returnFocusTo = document.activeElement;

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
    // UX-5: focus moves into the dialog; a destructive action starts on Cancel
    const start = typeInput || (card.dataset.destructive === "true" ? cancelBtn : okBtn);
    try { start.focus({ preventScroll: true }); } catch { start.focus(); }
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
    if (returnFocusTo && typeof returnFocusTo.focus === 'function' && document.contains(returnFocusTo)) {
      try { returnFocusTo.focus({ preventScroll: true }); } catch { /* the element went away */ }
    }
  };

  const onCancelClick = (e) => {
    if (e) e.preventDefault();
    cleanup();
    if (onCancel) onCancel();
  };
  const onOkClick = (e) => {
    if (e) e.preventDefault();
    if (okBtn.disabled) return;
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
    } else if (e.key === "Enter" && e.target === typeInput) {
      onOkClick(e);
    } else if (e.key === "Tab") {
      // UX-5: Tab stays inside the dialog
      const items = _focusables(card);
      if (!items.length) return;
      const i = items.indexOf(document.activeElement);
      const next = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : (i === -1 || i === items.length - 1 ? 0 : i + 1);
      e.preventDefault();
      items[next].focus();
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
    ? `<textarea id="prompt-toast-input" placeholder="${escapeHtml(placeholder)}" style="width: 100%; box-sizing: border-box; background: var(--lt-b-00000099, rgba(0,0,0,0.6)); border: 1px solid var(--lt-r-00f0ff66, rgba(0, 240, 255, 0.4)); padding: 9px 12px; color: var(--zn-text-strong); border-radius: 6px; font-size: 13px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; outline: none; min-height: 96px; resize: vertical; line-height: 1.45;">${escapeHtml(defaultVal || '')}</textarea>`
    : `<input type="${inputType}" id="prompt-toast-input" placeholder="${escapeHtml(placeholder)}" style="width: 100%; box-sizing: border-box; background: var(--lt-b-00000099, rgba(0,0,0,0.6)); border: 1px solid var(--lt-r-00f0ff66, rgba(0, 240, 255, 0.4)); padding: 9px 12px; color: var(--zn-text-strong); border-radius: 6px; font-size: 13px; outline: none;" value="${escapeHtml(defaultVal || '')}" />`;

  const safePromptMsg = options.allowHtml === false
    ? escapeHtml(msg || "")
    : (options.allowHtml || (msg && /<[a-z0-9]+/i.test(msg)))
      ? sanitizeModalHtml(msg || "")
      : escapeHtml(msg || "");

  card.innerHTML = `
    <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; border-bottom: 1px solid var(--zn-line-8); background: var(--lt-b-00f0ff14, rgba(0, 240, 255, 0.08));" id="confirm-toast-header-bg" data-dialog-header>
      <div style="display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; color: var(--lt-ink-brand, var(--brand, #00f0ff));" id="confirm-toast-title">
        <span>${icon}</span> ${escapeHtml(title || "Rename")}
      </div>
      <button type="button" id="confirm-toast-close" class="win-btn close-btn" title="${t('jobs.cancel', 'Cancel')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
    </div>
    <div style="padding: 16px 20px;">
      <div style="font-size: var(--zn-fs-xs); color: var(--zn-text-soft); margin-bottom: 12px; line-height: 1.5;">${safePromptMsg}</div>
      ${inputHtml}
      <div style="display: flex; gap: 10px; margin-top: 16px; justify-content: flex-end; align-items: center;">
        <button id="confirm-toast-cancel" class="btn-pill-toggle is-small">${escapeHtml(cancelText)}</button>
        <button id="confirm-toast-ok" class="btn-pill-toggle is-primary is-small">${escapeHtml(okText)}</button>
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

