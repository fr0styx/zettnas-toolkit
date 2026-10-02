import { ZettEventBus } from './event-bus.js';

export function showConfirmToast(title, msg, onConfirm) {
    ZettEventBus.dispatchEvent(new CustomEvent('toast:confirm', { detail: { title, msg, onConfirm } }));
};
export function showToast(msg, type="error") {
    ZettEventBus.dispatchEvent(new CustomEvent('toast:show', { detail: { msg, type } }));
};
window.addEventListener('DOMContentLoaded', () => {
    const $ = (id) => document.getElementById(id);
    let copyToastMinimized = false;
    let _customToastActive = false; // Add this locally!

    function _showToast(msg, type="error") {
  _customToastActive = true;
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
      }, 300);
  }, 8000);
}
    

    ZettEventBus.addEventListener('toast:confirm', (e) => _showConfirmToast(e.detail.title, e.detail.msg, e.detail.onConfirm));
    ZettEventBus.addEventListener('toast:show', (e) => _showToast(e.detail.msg, e.detail.type));

    ZettEventBus.addEventListener('copy_state_update', (e) => {
        const state = e.detail;
        const prog = state.progress || {};

    });
});
