import { ZettEventBus } from './event-bus.js';
import { state } from './state.js';

export function showConfirmToast(title, msg, onConfirm) {
  ZettEventBus.emit('toast:confirm', { title, msg, onConfirm });
}

export function showToast(msg, type = "error") {
  ZettEventBus.emit('toast:show', { msg, type });
}

window.showToast = showToast;
window.showConfirmToast = showConfirmToast;

window.addEventListener('DOMContentLoaded', () => {
  let _customToastActive = false;

  function _showConfirmToast(title, msg, onConfirm) {
    if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
    let modal = document.getElementById("confirm-toast-modal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "confirm-toast-modal";
      modal.className = "smart-modal-backdrop";
      modal.style.zIndex = "10006";
      modal.style.display = "none";
      modal.innerHTML = `
        <div class="smart-modal-window" style="width: 440px; max-width: 90vw;">
          <div class="smart-modal-header">
            <div class="smart-modal-title" id="confirm-toast-title">Confirm Action</div>
            <button class="btn-tool-close" id="confirm-toast-close">&times;</button>
          </div>
          <div class="smart-modal-body" style="padding: 16px 20px;">
            <div id="confirm-toast-msg" style="font-size: 12px; color: #cbd5e1; line-height: 1.5;"></div>
            <div style="display: flex; gap: 10px; margin-top: 16px; justify-content: flex-end;">
              <button class="btn-save-preset" id="confirm-toast-cancel" style="padding: 6px 14px; background: transparent; border-color: rgba(255,255,255,0.15);">Cancel</button>
              <button class="btn-save-preset" id="confirm-toast-ok" style="padding: 6px 14px; background: var(--ok2); color: #0a0e13; border-color: var(--ok2); font-weight: 700;">Confirm</button>
            </div>
          </div>
        </div>
      `;
      document.body.appendChild(modal);
    }

    const titleEl = document.getElementById("confirm-toast-title");
    const msgEl = document.getElementById("confirm-toast-msg");
    const closeBtn = document.getElementById("confirm-toast-close");
    const cancelBtn = document.getElementById("confirm-toast-cancel");
    const okBtn = document.getElementById("confirm-toast-ok");

    if (titleEl) titleEl.textContent = title || "Confirm Action";
    if (msgEl) msgEl.textContent = msg || "Are you sure you want to proceed?";

    const close = () => {
      modal.classList.remove("open");
      modal.style.opacity = "0";
      modal.style.pointerEvents = "none";
      modal.style.display = "none";
    };

    closeBtn.onclick = close;
    cancelBtn.onclick = close;
    modal.onclick = (e) => {
      if (e.target === modal) close();
    };
    okBtn.onclick = () => {
      close();
      if (typeof onConfirm === "function") onConfirm();
    };

    modal.style.display = "flex";
    modal.classList.add("open");
    modal.style.opacity = "1";
    modal.style.pointerEvents = "auto";
  }

  function _showToast(msg, type = "error") {
    if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
    _customToastActive = true;
    window._customToastActive = true;
    const toast = document.getElementById("copy-toast");
    const backdrop = document.getElementById("copy-toast-backdrop");
    if (!toast) return;

    toast.style.opacity = "1";
    toast.style.pointerEvents = "auto";
    toast.style.transition = "none";

    if (backdrop) {
      backdrop.style.opacity = "1";
      backdrop.style.pointerEvents = "auto";
    }

    toast.style.boxShadow = "0 0 40px rgba(0,0,0,0.8)";
    toast.style.bottom = "50%";
    toast.style.right = "50%";
    toast.style.transform = "translate(50%, 50%) scale(1.2)";

    const titleEl = toast.querySelector(".smart-modal-title");
    if (titleEl) titleEl.innerHTML = `<svg class="ic ic-sm" style="margin-right:4px;"><use href="#i-storage"/></svg> System Notification`;

    const statusEl = document.getElementById("copy-toast-status");
    if (statusEl) statusEl.textContent = type === "error" ? "Error!" : "Success!";

    const barEl = document.getElementById("copy-toast-bar");
    if (barEl) {
      barEl.style.width = "100%";
      barEl.style.background = type === "error" ? "#e74c3c" : "#2ecc71";
    }

    const fileEl = document.getElementById("copy-toast-file");
    if (fileEl) fileEl.textContent = msg;

    const timeEl = document.getElementById("copy-toast-time");
    if (timeEl) timeEl.textContent = "Closing automatically...";

    const pctEl = document.getElementById("copy-toast-pct");
    if (pctEl) pctEl.textContent = "";

    setTimeout(() => {
      toast.style.transition = "opacity 0.3s ease, transform 0.3s ease";
      toast.style.opacity = "0";
      toast.style.pointerEvents = "none";
      if (backdrop) {
        backdrop.style.opacity = "0";
        backdrop.style.pointerEvents = "none";
      }
      setTimeout(() => {
        if (titleEl) titleEl.innerHTML = `<svg class="ic ic-sm" style="margin-right:4px;"><use href="#i-storage"/></svg> Media card ingest`;
        _customToastActive = false;
        window._customToastActive = false;
      }, 300);
    }, 5000);
  }

  ZettEventBus.on('toast:confirm', (detail) => _showConfirmToast(detail.title, detail.msg, detail.onConfirm));
  ZettEventBus.on('toast:show', (detail) => _showToast(detail.msg, detail.type));
});
