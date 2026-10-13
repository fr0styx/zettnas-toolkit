import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';

let _activePreviewModal = null;
let _previewAbortController = null;

export async function openFilePreviewModal(path, name) {
  closeFilePreviewModal();

  const fileName = name || (path ? path.split('/').filter(Boolean).pop() : 'Preview');
  const overlay = document.createElement('div');
  overlay.id = 'quicklook-modal-overlay';
  overlay.className = 'quicklook-modal-overlay';
  overlay.innerHTML = `
    <div class="quicklook-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(fileName)}">
      <div class="quicklook-header">
        <div class="quicklook-title">
          <span>👁️</span>
          <span>${escapeHtml(fileName)}</span>
          <span class="quicklook-meta" id="quicklook-meta">Loading preview...</span>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <button class="btn-pill-toggle" id="quicklook-copy-btn" style="display:none; font-size:11px; padding:3px 8px;">📋 Copy</button>
          <button class="quicklook-close-btn" id="quicklook-close-btn" title="Close (Escape)" aria-label="Close">✕</button>
        </div>
      </div>
      <div class="quicklook-body" id="quicklook-body">
        <div style="display:flex; flex-direction:column; align-items:center; gap:12px; color:var(--muted);">
          <div class="spinner" style="width:28px; height:28px; border:2px solid rgba(255,255,255,0.2); border-top-color:var(--accent-cyan, #0ea5e9); border-radius:50%; animation:spin 0.8s linear infinite;"></div>
          <span style="font-size:12px;">Loading preview...</span>
        </div>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);
  _activePreviewModal = overlay;

  const closeBtn = overlay.querySelector('#quicklook-close-btn');
  const bodyEl = overlay.querySelector('#quicklook-body');
  const metaEl = overlay.querySelector('#quicklook-meta');
  const copyBtn = overlay.querySelector('#quicklook-copy-btn');

  const handleClose = () => closeFilePreviewModal();
  closeBtn?.addEventListener('click', handleClose);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) handleClose();
  });

  const onKeydown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      handleClose();
    }
  };
  window.addEventListener('keydown', onKeydown, { once: true });

  _previewAbortController = new AbortController();

  try {
    const res = await api.get(`/api/fs/preview?path=${encodeURIComponent(path)}`, {
      signal: _previewAbortController.signal,
    });

    if (!res || res.status !== 'ok') {
      throw new Error(res?.detail || 'Failed to generate preview');
    }

    const szStr = res.size !== undefined ? ` • ${formatSize(res.size)}` : '';

    if (res.type === 'image') {
      metaEl.textContent = `Image${szStr}`;
      const imgUrl = `/api/fs/download?path=${encodeURIComponent(path)}`;
      bodyEl.innerHTML = `<img src="${imgUrl}" class="quicklook-img" alt="${escapeHtml(fileName)}" />`;
    } else if (res.type === 'media') {
      const isVideo = ['.mp4', '.mkv', '.webm', '.mov', '.avi'].includes(res.ext);
      metaEl.textContent = `${isVideo ? 'Video' : 'Audio'}${szStr}`;
      const streamUrl = `/api/fs/stream?path=${encodeURIComponent(path)}`;
      if (isVideo) {
        bodyEl.innerHTML = `<video controls autoplay class="quicklook-video" src="${streamUrl}"></video>`;
      } else {
        bodyEl.innerHTML = `
          <div style="display:flex; flex-direction:column; align-items:center; gap:16px;">
            <div style="font-size:48px;">🎵</div>
            <audio controls autoplay class="quicklook-audio" src="${streamUrl}"></audio>
          </div>
        `;
      }
    } else if (res.type === 'pdf') {
      metaEl.textContent = `PDF Document${szStr}`;
      const pdfUrl = `/api/fs/download?path=${encodeURIComponent(path)}`;
      bodyEl.innerHTML = `<iframe src="${pdfUrl}" style="width:100%; height:100%; border:none; border-radius:6px;"></iframe>`;
    } else if (res.type === 'text') {
      const lines = res.lines_count || 1;
      metaEl.textContent = `${lines} line${lines === 1 ? '' : 's'}${szStr}${res.truncated ? ' (first 64KB)' : ''}`;
      bodyEl.innerHTML = `<pre class="quicklook-code"><code>${escapeHtml(res.content || '')}</code></pre>`;
      if (copyBtn) {
        copyBtn.style.display = 'block';
        copyBtn.onclick = async () => {
          try {
            await navigator.clipboard.writeText(res.content || '');
            showToast(t('common.copied', 'Copied to clipboard'));
          } catch (_) {
            showToast('Failed to copy');
          }
        };
      }
    } else if (res.type === 'hex') {
      metaEl.textContent = `Binary Hex Preview (1KB)${szStr}`;
      const dumpText = Array.isArray(res.hex_dump) ? res.hex_dump.join('\n') : '';
      bodyEl.innerHTML = `<pre class="quicklook-hex"><code>${escapeHtml(dumpText)}</code></pre>`;
    } else {
      metaEl.textContent = `Binary File${szStr}`;
      bodyEl.innerHTML = `
        <div style="display:flex; flex-direction:column; align-items:center; gap:12px; color:var(--muted);">
          <div style="font-size:36px;">📄</div>
          <span>Preview not available for this file type.</span>
        </div>
      `;
    }
  } catch (err) {
    if (err.name === 'AbortError') return;
    metaEl.textContent = 'Preview error';
    bodyEl.innerHTML = `
      <div style="display:flex; flex-direction:column; align-items:center; gap:8px; color:var(--crit, #ff5c5c);">
        <div style="font-size:32px;">⚠️</div>
        <span style="font-size:12px; font-weight:600;">${escapeHtml(err.message || 'Unable to preview file')}</span>
      </div>
    `;
  }
}

export function closeFilePreviewModal() {
  if (_previewAbortController) {
    _previewAbortController.abort();
    _previewAbortController = null;
  }
  if (_activePreviewModal) {
    _activePreviewModal.remove();
    _activePreviewModal = null;
  }
}

function formatSize(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

window.openFilePreviewModal = openFilePreviewModal;
window.closeFilePreviewModal = closeFilePreviewModal;
