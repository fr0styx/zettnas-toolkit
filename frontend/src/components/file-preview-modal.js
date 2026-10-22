import { api, auth } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';

import { formatBytes } from '../format.js';
import {
  ICONS,
  isImageName,
  isPreviewableName,
  displayImageUrl,
  originalImageUrl,
  thumbUrl,
  screenMaxDim,
  loadFolderGallery,
  renderMarkdown,
  srtToVtt,
  getResume,
  setResume,
  attachGestures,
} from './viewer-kit.js';
let _activePreviewModal = null;
let _previewAbortController = null;
let _previewKeydownListener = null;
let _activeVideoController = null;

// Session state for gallery navigation and pan/zoom transforms
let _gallery = [];
let _currentIndex = 0;
let _currentPath = null;
let _currentName = null;
let _currentAiMeta = null;
let _currentMeta = null;

let _zoom = 1.0;
let _panX = 0;
let _panY = 0;
let _rotation = 0;
let _flipH = false;
let _isDragging = false;
let _dragStartX = 0;
let _dragStartY = 0;
let _isMaximized = false;
let _isInfoOpen = false;
let _isFilmstripOpen = true;

const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg', '.bmp', '.ico', '.tiff', '.heic', '.heif']);
const MEDIA_EXTS = new Set(['.mp4', '.mkv', '.webm', '.mov', '.avi', '.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a']);

function isImageFile(filename) {
  if (!filename) return false;
  const ext = '.' + filename.split('.').pop().toLowerCase();
  return IMAGE_EXTS.has(ext);
}

function isPreviewableFile(filename) {
  if (!filename) return false;
  const ext = '.' + filename.split('.').pop().toLowerCase();
  return IMAGE_EXTS.has(ext) || MEDIA_EXTS.has(ext);
}

export async function openFilePreviewModal(path, name, aiMeta = null, fileList = null) {
  closeFilePreviewModal();

  _currentPath = path;
  _currentName = name || (path ? path.split('/').filter(Boolean).pop() : 'Preview');
  _currentAiMeta = aiMeta;
  _currentMeta = null;

  _zoom = 1.0;
  _panX = 0;
  _panY = 0;
  _rotation = 0;
  _flipH = false;
  _isDragging = false;
  _isMaximized = false;
  _isInfoOpen = false;
  _isFilmstripOpen = true;

  // Extract gallery playlist of sibling previewable files
  let candidateList = fileList;
  if (!candidateList && typeof window !== 'undefined') {
    if (typeof window.getActiveFmInstance === 'function') {
      const inst = window.getActiveFmInstance();
      if (inst && Array.isArray(inst.fileList) && inst.fileList.length > 0) {
        candidateList = inst.fileList;
      }
    }
  }

  if (Array.isArray(candidateList) && candidateList.length > 0) {
    const isCurImg = isImageFile(_currentName);
    _gallery = candidateList.filter((f) => {
      if (!f || f.is_dir || f.name === '..') return false;
      return isCurImg ? isImageFile(f.name) : isPreviewableFile(f.name);
    });
  } else {
    _gallery = [];
  }

  // Opened from search, AI results or another window: next/previous follow the file's own folder
  if (_gallery.length <= 1 && !fileList && isPreviewableName(_currentName)) {
    try {
      const siblings = await Promise.race([
        loadFolderGallery(_currentPath, (u) => api.get(u), { imagesOnly: isImageName(_currentName) }),
        new Promise((resolve) => setTimeout(() => resolve([]), 2500)),
      ]);
      if (siblings.length > 1) _gallery = siblings;
    } catch (_) {
      // the single file still opens
    }
  }

  if (_gallery.length === 0) {
    _gallery = [{ path: _currentPath, name: _currentName }];
    _currentIndex = 0;
  } else {
    _currentIndex = _gallery.findIndex((item) => item.path === _currentPath);
    if (_currentIndex === -1) {
      _currentIndex = 0;
      _gallery.unshift({ path: _currentPath, name: _currentName });
    }
  }

  const overlay = document.createElement('div');
  overlay.id = 'quicklook-modal-overlay';
  overlay.className = 'quicklook-modal-overlay';
  overlay.innerHTML = `
    <div class="quicklook-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(_currentName)}" id="quicklook-modal-dialog">
      <div class="quicklook-header" id="quicklook-header">
        <div class="quicklook-title">
          <span class="quicklook-title-icon">${ICONS.eye}</span>
          <span class="quicklook-title-text" id="quicklook-title-text">${escapeHtml(_currentName)}</span>
          <span class="quicklook-meta" id="quicklook-meta">Loading preview...</span>
          <span class="quicklook-counter-pill" id="quicklook-counter-pill" style="display:none;"></span>
        </div>
        <div class="quicklook-toolbar" id="quicklook-toolbar">
          <div class="quicklook-btn-group" id="quicklook-image-tools" style="display:none;">
            <button type="button" class="quicklook-btn" id="ql-zoom-out" title="${t('preview.zoom_out', 'Zoom Out (-)')}" aria-label="${t('preview.zoom_out', 'Zoom Out (-)')}">${ICONS.zoomOut}</button>
            <span class="quicklook-zoom-pill" id="quicklook-zoom-pill" title="${t('preview.fit', 'Fit to screen')}">Fit</span>
            <button type="button" class="quicklook-btn" id="ql-zoom-in" title="${t('preview.zoom_in', 'Zoom In (+)')}" aria-label="${t('preview.zoom_in', 'Zoom In (+)')}">${ICONS.zoomIn}</button>
            <button type="button" class="quicklook-btn" id="ql-actual-size" title="${t('preview.actual_size', '100%')}" aria-label="${t('preview.actual_size', '100%')}">1:1</button>
            <button type="button" class="quicklook-btn" id="ql-rotate-ccw" title="${t('preview.rotate_ccw', 'Rotate 90° Left')}" aria-label="${t('preview.rotate_ccw', 'Rotate 90° Left')}">${ICONS.rotateLeft}</button>
            <button type="button" class="quicklook-btn" id="ql-rotate-cw" title="${t('preview.rotate_cw', 'Rotate 90° Right (R)')}" aria-label="${t('preview.rotate_cw', 'Rotate 90° Right (R)')}">${ICONS.rotateRight}</button>
            <button type="button" class="quicklook-btn" id="ql-flip-h" title="${t('preview.flip', 'Flip Horizontally')}" aria-label="${t('preview.flip', 'Flip Horizontally')}">${ICONS.flip}</button>
          </div>
          <div class="quicklook-btn-group">
            <button type="button" class="quicklook-btn" id="ql-info-toggle" style="display:none;" title="${t('preview.info', 'Photo Details & EXIF (I)')}" aria-label="${t('preview.info', 'Photo Details & EXIF (I)')}">${ICONS.info}</button>
            <button type="button" class="quicklook-btn" id="ql-filmstrip-toggle" style="display:none;" title="${t('preview.filmstrip', 'Toggle Filmstrip')}" aria-label="${t('preview.filmstrip', 'Toggle Filmstrip')}">${ICONS.filmstrip}</button>
            <button type="button" class="quicklook-btn" id="quicklook-copy-btn" title="${t('preview.copy', 'Copy Image / Path')}" aria-label="${t('preview.copy', 'Copy Image / Path')}">${ICONS.copy}</button>
            <button type="button" class="quicklook-btn" id="ql-download-btn" title="${t('preview.download', 'Download')}" aria-label="${t('preview.download', 'Download')}">${ICONS.download}</button>
            <button type="button" class="quicklook-btn" id="ql-maximize-btn" title="${t('preview.maximize', 'Fullscreen (F)')}" aria-label="${t('preview.maximize', 'Fullscreen (F)')}">${ICONS.maximize}</button>
          </div>
        </div>
        <button type="button" class="quicklook-close-btn" id="quicklook-close-btn" title="${t('preview.close', 'Close (Esc)')}" aria-label="${t('preview.close', 'Close (Esc)')}">${ICONS.close}</button>
      </div>
      <div class="quicklook-body" id="quicklook-body">
        <div style="display:flex; flex-direction:column; align-items:center; gap:12px; color:var(--muted);">
          <div class="spinner" style="width:28px; height:28px; border:2px solid rgba(255,255,255,0.2); border-top-color:var(--accent-cyan, #0ea5e9); border-radius:50%; animation:spin 0.8s linear infinite;"></div>
          <span style="font-size:12px;">Loading preview...</span>
        </div>
      </div>
      <div class="quicklook-inspector" id="quicklook-inspector">
        <div class="quicklook-inspector-header">
          <span>ℹ️ ${escapeHtml(t('preview.info', 'Photo Details & EXIF'))}</span>
          <button type="button" class="quicklook-close-btn" id="ql-inspector-close" style="padding:2px 6px;" aria-label="${t('preview.close', 'Close (Esc)')}">${ICONS.close}</button>
        </div>
        <div class="quicklook-inspector-content" id="quicklook-inspector-content"></div>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);
  _activePreviewModal = overlay;

  bindModalGlobalEvents(overlay);

  await loadCurrentItem();
}

function bindModalGlobalEvents(overlay) {
  const closeBtn = overlay.querySelector('#quicklook-close-btn');
  const handleClose = () => closeFilePreviewModal();

  closeBtn?.addEventListener('click', handleClose);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) handleClose();
  });

  const maxBtn = overlay.querySelector('#ql-maximize-btn');
  maxBtn?.addEventListener('click', () => toggleMaximize());

  const infoBtn = overlay.querySelector('#ql-info-toggle');
  infoBtn?.addEventListener('click', () => toggleInspector());

  const inspectorClose = overlay.querySelector('#ql-inspector-close');
  inspectorClose?.addEventListener('click', () => toggleInspector(false));

  const filmstripBtn = overlay.querySelector('#ql-filmstrip-toggle');
  filmstripBtn?.addEventListener('click', () => toggleFilmstrip());

  const downloadBtn = overlay.querySelector('#ql-download-btn');
  downloadBtn?.addEventListener('click', () => triggerDownload());

  const copyBtn = overlay.querySelector('#quicklook-copy-btn');
  copyBtn?.addEventListener('click', () => triggerCopy());

  // Image transform buttons
  overlay.querySelector('#ql-zoom-in')?.addEventListener('click', () => zoomIn());
  overlay.querySelector('#ql-zoom-out')?.addEventListener('click', () => zoomOut());
  overlay.querySelector('#quicklook-zoom-pill')?.addEventListener('click', () => toggleZoomFitActual());
  overlay.querySelector('#ql-actual-size')?.addEventListener('click', () => setActualSize());
  overlay.querySelector('#ql-rotate-cw')?.addEventListener('click', () => rotateCw());
  overlay.querySelector('#ql-rotate-ccw')?.addEventListener('click', () => rotateCcw());
  overlay.querySelector('#ql-flip-h')?.addEventListener('click', () => flipH());

  _previewKeydownListener = (e) => {
    // Ignore keybindings if the user is typing in an active text input or textarea
    const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
    if (activeTag === 'input' || activeTag === 'textarea' || document.activeElement?.isContentEditable) {
      if (e.key === 'Escape') closeFilePreviewModal();
      return;
    }

    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      closeFilePreviewModal();
      return;
    }

    // Video-specific keybindings when video player is active
    if (_activeVideoController) {
      if (e.key === 'PageDown' || e.key === 'PageUp' || (e.shiftKey && (e.key === 'ArrowRight' || e.key === 'ArrowLeft'))) {
        if (_gallery.length > 1) {
          e.preventDefault();
          e.stopPropagation();
          navigateGallery(e.key === 'PageDown' || e.key === 'ArrowRight' ? 1 : -1);
        }
        return;
      }
      if (e.code === 'Space' || e.key === 'k' || e.key === 'K') {
        e.preventDefault();
        e.stopPropagation();
        _activeVideoController.togglePlayPause();
        return;
      }
      if (e.key === 'ArrowRight' || e.key === 'l' || e.key === 'L') {
        e.preventDefault();
        e.stopPropagation();
        _activeVideoController.seekDelta(10);
        return;
      }
      if (e.key === 'ArrowLeft' || e.key === 'j' || e.key === 'J') {
        e.preventDefault();
        e.stopPropagation();
        _activeVideoController.seekDelta(-10);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        _activeVideoController.setVolumeDelta(0.1);
        return;
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        e.stopPropagation();
        _activeVideoController.setVolumeDelta(-0.1);
        return;
      }
      if (e.key === 'm' || e.key === 'M') {
        e.preventDefault();
        e.stopPropagation();
        _activeVideoController.toggleMute();
        return;
      }
      if (e.key === 'f' || e.key === 'F') {
        e.preventDefault();
        e.stopPropagation();
        toggleMaximize();
        return;
      }
      if (e.key === 'p' || e.key === 'P') {
        e.preventDefault();
        e.stopPropagation();
        _activeVideoController.togglePip();
        return;
      }
      if (e.key >= '0' && e.key <= '9') {
        e.preventDefault();
        e.stopPropagation();
        _activeVideoController.seekPercent(parseInt(e.key, 10) / 10);
        return;
      }
      if (e.key === '[') {
        e.preventDefault();
        _activeVideoController.stepSpeed(-1);
        return;
      }
      if (e.key === ']') {
        e.preventDefault();
        _activeVideoController.stepSpeed(1);
        return;
      }
      return;
    }

    // Default image / document preview keybindings
    if (e.code === 'Space') {
      e.preventDefault();
      e.stopPropagation();
      closeFilePreviewModal();
      return;
    }

    if (e.key === 'ArrowRight') {
      if (_gallery.length > 1) {
        e.preventDefault();
        e.stopPropagation();
        navigateGallery(1);
      }
      return;
    }

    if (e.key === 'ArrowLeft') {
      if (_gallery.length > 1) {
        e.preventDefault();
        e.stopPropagation();
        navigateGallery(-1);
      }
      return;
    }

    if (e.key === '+' || e.key === '=') {
      e.preventDefault();
      zoomIn();
      return;
    }

    if (e.key === '-' || e.key === '_') {
      e.preventDefault();
      zoomOut();
      return;
    }

    if (e.key === '0') {
      e.preventDefault();
      resetZoom();
      return;
    }

    if (e.key === '1') {
      e.preventDefault();
      setActualSize();
      return;
    }

    if (e.key === 'r' || e.key === 'R') {
      e.preventDefault();
      rotateCw();
      return;
    }

    if (e.key === 'i' || e.key === 'I') {
      e.preventDefault();
      toggleInspector();
      return;
    }

    if (e.key === 'f' || e.key === 'F' || e.key === 'm' || e.key === 'M') {
      e.preventDefault();
      toggleMaximize();
      return;
    }
  };
  window.addEventListener('keydown', _previewKeydownListener);
}

async function loadCurrentItem() {
  if (!_activePreviewModal) return;

  if (_activeVideoController) {
    if (_activeVideoController.videoEl && !_activeVideoController.videoEl.paused) {
      try {
        _activeVideoController.videoEl.pause();
      } catch (_) {}
    }
    _activeVideoController = null;
  }

  const currentItem = _gallery[_currentIndex] || { path: _currentPath, name: _currentName };
  _currentPath = currentItem.path;
  _currentName = currentItem.name;

  // Reset transforms
  _zoom = 1.0;
  _panX = 0;
  _panY = 0;
  _rotation = 0;
  _flipH = false;
  _isDragging = false;

  const titleEl = _activePreviewModal.querySelector('#quicklook-title-text');
  const metaEl = _activePreviewModal.querySelector('#quicklook-meta');
  const counterPill = _activePreviewModal.querySelector('#quicklook-counter-pill');
  const bodyEl = _activePreviewModal.querySelector('#quicklook-body');
  const imgTools = _activePreviewModal.querySelector('#quicklook-image-tools');
  const infoBtn = _activePreviewModal.querySelector('#ql-info-toggle');
  const filmstripBtn = _activePreviewModal.querySelector('#ql-filmstrip-toggle');

  if (titleEl) titleEl.textContent = _currentName;
  if (metaEl) metaEl.textContent = 'Loading...';

  // Update gallery counter
  if (_gallery.length > 1 && counterPill) {
    counterPill.textContent = `${_currentIndex + 1} / ${_gallery.length}`;
    counterPill.style.display = 'inline-block';
  } else if (counterPill) {
    counterPill.style.display = 'none';
  }

  // Synchronize background File Explorer selection to match currently viewed item
  if (typeof window !== 'undefined' && typeof window.getActiveFmInstance === 'function') {
    const inst = window.getActiveFmInstance();
    if (inst && Array.isArray(inst.fileList) && inst.fileList.some((f) => f.path === _currentPath)) {
      inst.selectedPaths.clear();
      inst.selectedPaths.add(_currentPath);
      inst.lastSelectedIndex = inst.fileList.findIndex((f) => f.path === _currentPath);
      if (typeof inst.updateRowSelectionUI === 'function') inst.updateRowSelectionUI();
      if (typeof inst.updateSelectionToolbar === 'function') inst.updateSelectionToolbar();
    }
  }

  // Handle Standby Guard preview
  if (_currentAiMeta && _currentAiMeta.standbySafe) {
    if (imgTools) imgTools.style.display = 'none';
    if (infoBtn) infoBtn.style.display = 'none';
    if (filmstripBtn) filmstripBtn.style.display = 'none';

    metaEl.textContent = '💤 NVMe RAG Cache (Zero Disk Wake)';
    const isPhoto = isImageFile(_currentName);
    const thumbHtml = isPhoto && _currentAiMeta.thumbnailUrl
      ? `<img src="${escapeHtml(_currentAiMeta.thumbnailUrl)}" class="quicklook-img" alt="${escapeHtml(_currentName)}" style="max-height:360px; border-radius:8px; object-fit:contain;" />`
      : '';
    const excerptHtml = _currentAiMeta.excerpt
      ? `<pre class="quicklook-code" style="width:100%; max-height:280px; overflow:auto;"><code>${escapeHtml(_currentAiMeta.excerpt)}</code></pre>`
      : '';
    bodyEl.innerHTML = `
      <div style="display:flex; flex-direction:column; align-items:center; gap:14px; width:100%; padding:14px;">
        <div style="width:100%; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; padding:8px 12px; border-radius:8px; background:rgba(16,185,129,0.1); border:1px solid rgba(16,185,129,0.28); font-size:11.5px; color:#6ee7b7;">
          <span>💤 <strong>Standby Guard Active:</strong> Showing cached NVMe index preview without spinning up physical array disks.</span>
          <button type="button" class="btn-pill-toggle" id="btn-quicklook-wake-load" style="padding:4px 10px; font-size:11px; color:#38bdf8; border-color:rgba(56,189,248,0.4);">⚡ Load Full File from Disk</button>
        </div>
        ${thumbHtml}
        ${excerptHtml}
        <div style="font-size:11px; color:var(--muted); font-family:monospace;">${escapeHtml(_currentPath || '')}</div>
      </div>
    `;
    const wakeBtn = bodyEl.querySelector('#btn-quicklook-wake-load');
    if (wakeBtn) {
      wakeBtn.addEventListener('click', () => {
        _currentAiMeta = null;
        loadCurrentItem();
      });
    }
    return;
  }

  if (_previewAbortController) {
    _previewAbortController.abort();
  }
  _previewAbortController = new AbortController();

  try {
    const res = await api.get(`/api/fs/preview?path=${encodeURIComponent(_currentPath)}`, {
      signal: _previewAbortController.signal,
    });

    if (!res || res.status !== 'ok') {
      throw new Error(res?.detail || 'Failed to generate preview');
    }

    _currentMeta = res;
    const szStr = res.size !== undefined ? ` • ${formatSize(res.size)}` : '';

    if (res.type === 'image') {
      const dimStr = res.dimensions ? ` • ${res.dimensions}` : '';
      metaEl.textContent = `Image${szStr}${dimStr}`;

      if (imgTools) imgTools.style.display = 'flex';
      if (infoBtn) infoBtn.style.display = 'inline-flex';
      if (filmstripBtn && _gallery.length > 1) filmstripBtn.style.display = 'inline-flex';

      // A screen-sized copy loads fast on phones; 1:1 and deep zoom switch to the original
      renderImagePreview(bodyEl, displayImageUrl(_currentPath, screenMaxDim()), res);
      const shownImg = bodyEl.querySelector('#quicklook-img');
      if (shownImg) shownImg.dataset.original = originalImageUrl(_currentPath);
      preloadNeighbours();
      updateInspectorContent(res);
    } else {
      if (imgTools) imgTools.style.display = 'none';
      if (infoBtn) infoBtn.style.display = 'none';
      if (filmstripBtn) filmstripBtn.style.display = 'none';

      if (res.type === 'media') {
        const isVideo = ['.mp4', '.mkv', '.webm', '.mov', '.avi'].includes(res.ext);
        metaEl.textContent = `${isVideo ? 'Video' : 'Audio'}${szStr}`;
        const streamUrl = `/api/fs/stream?path=${encodeURIComponent(_currentPath)}`;
        if (isVideo) {
          renderVideoPlayer(bodyEl, streamUrl, res);
          addGalleryNav(bodyEl);
        } else {
          bodyEl.innerHTML = `
            <div style="display:flex; flex-direction:column; align-items:center; gap:16px;">
              <div style="font-size:52px;">🎵</div>
              <audio controls autoplay class="quicklook-audio" src="${streamUrl}"></audio>
            </div>
          `;
        }
      } else if (res.type === 'pdf') {
        metaEl.textContent = `PDF Document${szStr}`;
        const pdfUrl = `/api/fs/download?path=${encodeURIComponent(_currentPath)}`;
        bodyEl.innerHTML = `<iframe src="${pdfUrl}" style="width:100%; height:100%; border:none; border-radius:6px;"></iframe>`;
      } else if (res.type === 'text') {
        const lines = res.lines_count || 1;
        metaEl.textContent = `${lines} line${lines === 1 ? '' : 's'}${szStr}${res.truncated ? ' (first 64KB)' : ''}`;
        if (/\.(md|markdown)$/i.test(_currentName || '')) {
          bodyEl.innerHTML = `<article class="quicklook-markdown">${renderMarkdown(res.content || '')}</article>`;
        } else {
          bodyEl.innerHTML = `<pre class="quicklook-code"><code>${escapeHtml(res.content || '')}</code></pre>`;
        }
      } else if (res.type === 'hex') {
        metaEl.textContent = `Binary Hex Preview (1KB)${szStr}`;
        const dumpText = Array.isArray(res.hex_dump) ? res.hex_dump.join('\n') : '';
        bodyEl.innerHTML = `<pre class="quicklook-hex"><code>${escapeHtml(dumpText)}</code></pre>`;
      } else {
        metaEl.textContent = `Binary File${szStr}`;
        addGalleryNav(bodyEl);
        bodyEl.innerHTML = `
          <div style="display:flex; flex-direction:column; align-items:center; gap:12px; color:var(--muted);">
            <div style="font-size:36px;">📄</div>
            <span>Preview not available for this file type.</span>
          </div>
        `;
      }
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

function preloadNeighbours() {
  if (_gallery.length < 2) return;
  for (const d of [1, -1]) {
    const item = _gallery[(_currentIndex + d + _gallery.length) % _gallery.length];
    if (item && isImageName(item.name)) {
      const pre = new Image();
      pre.decoding = 'async';
      pre.src = displayImageUrl(item.path, screenMaxDim());
    }
  }
}

function useOriginalImage(img) {
  if (img && img.dataset.original && !img.dataset.isOriginal) {
    img.dataset.isOriginal = '1';
    img.src = img.dataset.original;
    return true;
  }
  return false;
}

// Prev/next buttons for views other than images (video, audio, documents)
function addGalleryNav(bodyEl) {
  if (_gallery.length <= 1 || bodyEl.querySelector('.quicklook-nav-btn')) return;
  const mk = (cls, dir, label, icon) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = `quicklook-nav-btn ${cls}`;
    b.setAttribute('aria-label', label);
    b.title = label;
    b.innerHTML = icon;
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      navigateGallery(dir);
    });
    return b;
  };
  bodyEl.prepend(mk('quicklook-prev-btn', -1, t('preview.prev', 'Previous (Left Arrow)'), ICONS.prev));
  bodyEl.append(mk('quicklook-next-btn', 1, t('preview.next', 'Next (Right Arrow)'), ICONS.next));
}

function renderImagePreview(bodyEl, imgUrl, meta) {
  const showNav = _gallery.length > 1;

  bodyEl.innerHTML = `
    ${showNav ? `<button type="button" class="quicklook-nav-btn quicklook-prev-btn" id="ql-nav-prev" title="${t('preview.prev', 'Previous (Left Arrow)')}" aria-label="${t('preview.prev', 'Previous (Left Arrow)')}">${ICONS.prev}</button>` : ''}
    <div class="quicklook-viewport" id="quicklook-viewport">
      <img src="${imgUrl}" class="quicklook-img" id="quicklook-img" alt="${escapeHtml(_currentName)}" draggable="false" />
    </div>
    ${showNav ? `<button type="button" class="quicklook-nav-btn quicklook-next-btn" id="ql-nav-next" title="${t('preview.next', 'Next (Right Arrow)')}" aria-label="${t('preview.next', 'Next (Right Arrow)')}">${ICONS.next}</button>` : ''}
    ${showNav ? `<div class="quicklook-filmstrip ${_isFilmstripOpen ? '' : 'collapsed'}" id="quicklook-filmstrip"></div>` : ''}
  `;

  const viewport = bodyEl.querySelector('#quicklook-viewport');
  const img = bodyEl.querySelector('#quicklook-img');

  if (img) {
    img.onload = () => {
      const w = img.naturalWidth;
      const h = img.naturalHeight;
      if (w && h) {
        if (!_currentMeta) _currentMeta = {};
        if (!_currentMeta.dimensions) {
          _currentMeta.dimensions = `${w} × ${h}`;
          const mp = Math.round((w * h) / 100000) / 10;
          if (mp > 0 && !_currentMeta.megapixels) _currentMeta.megapixels = `${mp} MP`;
          const metaEl = _activePreviewModal?.querySelector('#quicklook-meta');
          if (metaEl) {
            const szStr = _currentMeta.size !== undefined ? ` • ${formatSize(_currentMeta.size)}` : '';
            metaEl.textContent = `Image${szStr} • ${w} × ${h}`;
          }
          updateInspectorContent(_currentMeta);
        }
      }
    };
  }

  bodyEl.querySelector('#ql-nav-prev')?.addEventListener('click', (e) => {
    e.stopPropagation();
    navigateGallery(-1);
  });
  bodyEl.querySelector('#ql-nav-next')?.addEventListener('click', (e) => {
    e.stopPropagation();
    navigateGallery(1);
  });

  if (viewport && img) {
    bindPanZoomHandlers(viewport, img);
  }

  if (showNav) {
    renderFilmstrip(bodyEl.querySelector('#quicklook-filmstrip'));
  }
}

function bindPanZoomHandlers(viewport, img) {
  // Mouse Wheel Zoom centered at cursor
  viewport.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const mouseX = e.clientX - (rect.left + rect.width / 2);
    const mouseY = e.clientY - (rect.top + rect.height / 2);

    const factor = e.deltaY < 0 ? 1.15 : (1 / 1.15);
    const nextZoom = Math.min(10.0, Math.max(0.15, _zoom * factor));

    _panX = mouseX - (mouseX - _panX) * (nextZoom / _zoom);
    _panY = mouseY - (mouseY - _panY) * (nextZoom / _zoom);
    _zoom = nextZoom;

    applyTransform(img, viewport, false);
  }, { passive: false });

  // Touch: swipe for next/previous, pinch to zoom
  attachGestures(viewport, {
    get: () => ({ zoom: _zoom }),
    onSwipe: (dir) => navigateGallery(dir),
    onPinch: (z) => {
      _zoom = z;
      applyTransform(img, viewport, false);
    },
  });

  // Drag to pan
  viewport.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    if (e.target.closest('.quicklook-nav-btn') || e.target.closest('.quicklook-filmstrip')) return;
    if (!e.isPrimary || (e.pointerType !== 'mouse' && _zoom <= 1.05)) return; // a swipe or pinch, not a pan

    _isDragging = true;
    _dragStartX = e.clientX - _panX;
    _dragStartY = e.clientY - _panY;
    try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
    viewport.style.cursor = 'grabbing';
  });

  viewport.addEventListener('pointermove', (e) => {
    if (!_isDragging) return;
    _panX = e.clientX - _dragStartX;
    _panY = e.clientY - _dragStartY;
    applyTransform(img, viewport, false);
  });

  const endDrag = (e) => {
    if (!_isDragging) return;
    _isDragging = false;
    try { viewport.releasePointerCapture(e.pointerId); } catch (_) {}
    viewport.style.cursor = _zoom > 1.02 ? 'grab' : 'default';
  };
  viewport.addEventListener('pointerup', endDrag);
  viewport.addEventListener('pointercancel', endDrag);

  // Double click / Double tap toggle
  viewport.addEventListener('dblclick', (e) => {
    if (e.target.closest('.quicklook-nav-btn') || e.target.closest('.quicklook-filmstrip')) return;
    if (_zoom <= 1.05) {
      _zoom = 2.0;
    } else {
      _zoom = 1.0;
      _panX = 0;
      _panY = 0;
    }
    applyTransform(img, viewport, true);
  });
}

function applyTransform(img, viewport, withTransition = false) {
  if (!img) return;
  img.style.transition = withTransition ? 'transform 0.22s cubic-bezier(0.2, 0, 0, 1)' : 'none';
  img.style.transform = `translate3d(${_panX}px, ${_panY}px, 0px) scale(${_zoom}) rotate(${_rotation}deg) scaleX(${_flipH ? -1 : 1})`;
  if (_zoom > 1.6) useOriginalImage(img); // full detail when zooming in

  const zoomPill = _activePreviewModal?.querySelector('#quicklook-zoom-pill');
  if (zoomPill) {
    zoomPill.textContent = Math.abs(_zoom - 1.0) < 0.03 ? t('preview.fit', 'Fit') : `${Math.round(_zoom * 100)}%`;
  }

  if (viewport) {
    viewport.style.cursor = _zoom > 1.02 ? (_isDragging ? 'grabbing' : 'grab') : 'default';
  }
}

function zoomIn() {
  const img = _activePreviewModal?.querySelector('#quicklook-img');
  const viewport = _activePreviewModal?.querySelector('#quicklook-viewport');
  _zoom = Math.min(10.0, _zoom * 1.25);
  applyTransform(img, viewport, true);
}

function zoomOut() {
  const img = _activePreviewModal?.querySelector('#quicklook-img');
  const viewport = _activePreviewModal?.querySelector('#quicklook-viewport');
  _zoom = Math.max(0.15, _zoom / 1.25);
  applyTransform(img, viewport, true);
}

function resetZoom() {
  const img = _activePreviewModal?.querySelector('#quicklook-img');
  const viewport = _activePreviewModal?.querySelector('#quicklook-viewport');
  _zoom = 1.0;
  _panX = 0;
  _panY = 0;
  applyTransform(img, viewport, true);
}

function toggleZoomFitActual() {
  if (Math.abs(_zoom - 1.0) < 0.05) {
    setActualSize();
  } else {
    resetZoom();
  }
}

function setActualSize() {
  const img = _activePreviewModal?.querySelector('#quicklook-img');
  const viewport = _activePreviewModal?.querySelector('#quicklook-viewport');
  if (useOriginalImage(img)) {
    img.addEventListener('load', () => setActualSize(), { once: true });
    return;
  }
  if (img && img.naturalWidth && img.clientWidth) {
    _zoom = img.naturalWidth / img.clientWidth;
  } else {
    _zoom = 1.0;
  }
  _panX = 0;
  _panY = 0;
  applyTransform(img, viewport, true);
}

function rotateCw() {
  const img = _activePreviewModal?.querySelector('#quicklook-img');
  const viewport = _activePreviewModal?.querySelector('#quicklook-viewport');
  _rotation = (_rotation + 90) % 360;
  applyTransform(img, viewport, true);
}

function rotateCcw() {
  const img = _activePreviewModal?.querySelector('#quicklook-img');
  const viewport = _activePreviewModal?.querySelector('#quicklook-viewport');
  _rotation = (_rotation + 270) % 360;
  applyTransform(img, viewport, true);
}

function flipH() {
  const img = _activePreviewModal?.querySelector('#quicklook-img');
  const viewport = _activePreviewModal?.querySelector('#quicklook-viewport');
  _flipH = !_flipH;
  applyTransform(img, viewport, true);
}

function toggleMaximize() {
  const modal = _activePreviewModal?.querySelector('#quicklook-modal-dialog');
  const maxBtn = _activePreviewModal?.querySelector('#ql-maximize-btn');
  if (!modal) return;
  _isMaximized = !_isMaximized;
  modal.classList.toggle('maximized', _isMaximized);
  if (maxBtn) {
    maxBtn.innerHTML = _isMaximized ? ICONS.restore : ICONS.maximize;
    maxBtn.title = _isMaximized ? t('preview.restore', 'Exit Fullscreen') : t('preview.maximize', 'Fullscreen');
  }
}

function toggleInspector(forceState = null) {
  const inspector = _activePreviewModal?.querySelector('#quicklook-inspector');
  const infoBtn = _activePreviewModal?.querySelector('#ql-info-toggle');
  if (!inspector) return;
  _isInfoOpen = forceState !== null ? forceState : !_isInfoOpen;
  inspector.classList.toggle('open', _isInfoOpen);
  infoBtn?.classList.toggle('active', _isInfoOpen);
}

function toggleFilmstrip() {
  const filmstrip = _activePreviewModal?.querySelector('#quicklook-filmstrip');
  const stripBtn = _activePreviewModal?.querySelector('#ql-filmstrip-toggle');
  if (!filmstrip) return;
  _isFilmstripOpen = !_isFilmstripOpen;
  filmstrip.classList.toggle('collapsed', !_isFilmstripOpen);
  stripBtn?.classList.toggle('active', _isFilmstripOpen);
}

function renderFilmstrip(container) {
  if (!container || _gallery.length <= 1) return;

  container.innerHTML = _gallery
    .map((item, idx) => {
      const isCur = idx === _currentIndex;
      return `
        <div class="quicklook-thumb-item ${isCur ? 'active' : ''}" data-idx="${idx}" title="${escapeHtml(item.name)}">
          <img src="${thumbUrl(item.path)}" alt="${escapeHtml(item.name)}" loading="lazy" decoding="async" />
        </div>
      `;
    })
    .join('');

  container.querySelectorAll('.quicklook-thumb-item').forEach((thumb) => {
    thumb.addEventListener('click', (e) => {
      e.stopPropagation();
      const idx = parseInt(thumb.getAttribute('data-idx'), 10);
      if (!isNaN(idx) && idx !== _currentIndex) {
        _currentIndex = idx;
        loadCurrentItem();
      }
    });
  });

  // Scroll active thumbnail into view
  const activeThumb = container.querySelector('.quicklook-thumb-item.active');
  if (activeThumb && typeof activeThumb.scrollIntoView === 'function') {
    activeThumb.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  }
}

function updateInspectorContent(meta) {
  const contentEl = _activePreviewModal?.querySelector('#quicklook-inspector-content');
  if (!contentEl) return;

  const exif = meta.exif || {};
  const hasExif = Object.keys(exif).length > 0;

  let exposureTilesHtml = '';
  if (exif.shutter_speed || exif.aperture || exif.iso || exif.focal_length) {
    exposureTilesHtml = `
      <div>
        <div style="font-size:11px; font-weight:700; color:var(--accent-cyan, #0ea5e9); margin-bottom:6px;">${escapeHtml(t('preview.exposure', 'EXPOSURE'))}</div>
        <div class="quicklook-exif-grid">
          ${exif.shutter_speed ? `<div class="quicklook-exif-tile"><span class="quicklook-exif-label">Shutter</span><span class="quicklook-exif-val">${escapeHtml(exif.shutter_speed)}</span></div>` : ''}
          ${exif.aperture ? `<div class="quicklook-exif-tile"><span class="quicklook-exif-label">Aperture</span><span class="quicklook-exif-val">${escapeHtml(exif.aperture)}</span></div>` : ''}
          ${exif.iso ? `<div class="quicklook-exif-tile"><span class="quicklook-exif-label">ISO</span><span class="quicklook-exif-val">${escapeHtml(exif.iso)}</span></div>` : ''}
          ${exif.focal_length ? `<div class="quicklook-exif-tile"><span class="quicklook-exif-label">Focal Length</span><span class="quicklook-exif-val">${escapeHtml(exif.focal_length)}</span></div>` : ''}
        </div>
      </div>
    `;
  }

  let cameraCardHtml = '';
  if (exif.camera || exif.lens) {
    cameraCardHtml = `
      <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:12px;">
        <div style="font-size:11px; font-weight:700; color:var(--accent-cyan, #0ea5e9); margin-bottom:6px;">📷 ${escapeHtml(t('preview.camera', 'CAMERA & GEAR'))}</div>
        ${exif.camera ? `<div style="font-weight:700; color:#fff; font-size:13px;">${escapeHtml(exif.camera)}</div>` : ''}
        ${exif.lens ? `<div style="font-size:11.5px; color:#94a3b8; margin-top:2px;">${escapeHtml(exif.lens)}</div>` : ''}
      </div>
    `;
  }

  contentEl.innerHTML = `
    ${cameraCardHtml}
    ${exposureTilesHtml}
    <div>
      <div style="font-size:11px; font-weight:700; color:var(--accent-cyan, #0ea5e9); margin-bottom:6px;">${escapeHtml(t('preview.specs', 'FILE SPECIFICATIONS'))}</div>
      <div class="quicklook-prop-row">
        <span class="quicklook-prop-label">Dimensions</span>
        <span class="quicklook-prop-val">${escapeHtml(meta.dimensions || '—')}</span>
      </div>
      ${meta.megapixels ? `
      <div class="quicklook-prop-row">
        <span class="quicklook-prop-label">Resolution</span>
        <span class="quicklook-prop-val">${escapeHtml(meta.megapixels)}</span>
      </div>` : ''}
      <div class="quicklook-prop-row">
        <span class="quicklook-prop-label">File Size</span>
        <span class="quicklook-prop-val">${formatSize(meta.size || 0)}</span>
      </div>
      <div class="quicklook-prop-row">
        <span class="quicklook-prop-label">Format</span>
        <span class="quicklook-prop-val">${(meta.ext || '').toUpperCase().replace('.', '')} ${meta.color_mode ? `(${meta.color_mode})` : ''}</span>
      </div>
      ${exif.date_taken ? `
      <div class="quicklook-prop-row">
        <span class="quicklook-prop-label">Date Taken</span>
        <span class="quicklook-prop-val">${escapeHtml(exif.date_taken)}</span>
      </div>` : ''}
      <div class="quicklook-prop-row" style="flex-direction:column; align-items:flex-start; gap:4px; margin-top:6px;">
        <span class="quicklook-prop-label">Location</span>
        <div style="font-size:11px; color:#94a3b8; font-family:monospace; word-break:break-all; background:rgba(0,0,0,0.3); padding:4px 6px; border-radius:4px; width:100%;">${escapeHtml(meta.path || '')}</div>
      </div>
      <div style="margin-top:10px;">
        <button type="button" class="btn-pill-toggle" id="ql-copy-path-btn" style="width:100%; padding:6px; font-size:11px; text-align:center;">📋 ${escapeHtml(t('preview.copy_path', 'Copy File Path'))}</button>
      </div>
    </div>
  `;

  contentEl.querySelector('#ql-copy-path-btn')?.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(meta.path || '');
      showToast(t('common.copied', 'Copied path to clipboard!'), 'success');
    } catch (_) {
      showToast(t('toast.failed_to_copy', 'Failed to copy'), 'error');
    }
  });
}

function navigateGallery(direction) {
  if (_gallery.length <= 1) return;
  _currentIndex = (_currentIndex + direction + _gallery.length) % _gallery.length;
  loadCurrentItem();
}

function triggerDownload() {
  if (!_currentPath) return;
  const token = (auth && typeof auth.getToken === 'function' ? auth.getToken() : null) || '';
  const a = document.createElement('a');
  a.href = `/api/fs/download?path=${encodeURIComponent(_currentPath)}`;
  a.download = _currentName || 'download';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function triggerCopy() {
  if (!_currentPath) return;
  if (_currentMeta && _currentMeta.type === 'text') {
    try {
      await navigator.clipboard.writeText(_currentMeta.content || '');
      showToast(t('common.copied', 'Text copied to clipboard!'), 'success');
    } catch (_) {
      showToast(t('toast.failed_to_copy_text', 'Failed to copy text'), 'error');
    }
    return;
  }

  const token = (auth && typeof auth.getToken === 'function' ? auth.getToken() : null) || '';
  const isHeif = /\.(heic|heif)$/i.test(_currentPath || '');
  const imgUrl = isHeif
    ? `/api/fs/preview/image?path=${encodeURIComponent(_currentPath)}`
    : `/api/fs/download?path=${encodeURIComponent(_currentPath)}`;

  try {
    const resp = await fetch(imgUrl);
    const blob = await resp.blob();
    // Copy as PNG blob if supported
    if (typeof ClipboardItem !== 'undefined') {
      try {
        await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
        showToast(t('common.copied', 'Image copied to clipboard!'), 'success');
        return;
      } catch (_) {}
    }
    await navigator.clipboard.writeText(_currentPath);
    showToast(t('common.copied', 'File path copied to clipboard!'), 'info');
  } catch (_) {
    await navigator.clipboard.writeText(_currentPath);
    showToast(t('common.copied', 'File path copied to clipboard!'), 'info');
  }
}

function renderVideoPlayer(container, streamUrl, meta) {
  const isPipSupported = typeof document !== 'undefined' && 'pictureInPictureEnabled' in document && document.pictureInPictureEnabled;

  container.innerHTML = `
    <div class="quicklook-video-container" id="quicklook-video-container" tabindex="0">
      <video class="quicklook-video-element" id="quicklook-video-player" src="${escapeHtml(streamUrl)}" playsinline preload="metadata"></video>
      
      <!-- Floating Center Big Play/Pause Button -->
      <button type="button" class="quicklook-video-center-btn" id="ql-video-center-btn" aria-label="${escapeHtml(t('video.play', 'Play'))}">
        <svg class="ql-icon-play" viewBox="0 0 24 24" width="34" height="34" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
      </button>

      <!-- Transient badge for volume, speed, seek feedback -->
      <div class="quicklook-video-badge" id="ql-video-badge"></div>

      <!-- Glassmorphic HUD overlay -->
      <div class="quicklook-video-hud" id="quicklook-video-hud">
        <!-- Interactive Scrubber -->
        <div class="quicklook-video-scrub-container" id="ql-video-scrub-container">
          <div class="quicklook-video-scrub-track" id="ql-video-scrub-track">
            <div class="quicklook-video-buffer-bar" id="ql-video-buffer-bar" style="width: 0%;"></div>
            <div class="quicklook-video-progress-bar" id="ql-video-progress-bar" style="width: 0%;"></div>
            <div class="quicklook-video-scrub-thumb" id="ql-video-scrub-thumb" style="left: 0%;"></div>
          </div>
          <div class="quicklook-video-time-tooltip" id="ql-video-time-tooltip">00:00</div>
        </div>

        <!-- Controls Row -->
        <div class="quicklook-video-controls-row">
          <!-- Left Controls -->
          <div class="quicklook-video-ctrl-group">
            <button type="button" class="quicklook-vctrl-btn" id="ql-video-play-btn" title="${escapeHtml(t('video.play', 'Play'))} (Space / K)">
              <svg class="ql-icon-play" viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
              <svg class="ql-icon-pause" viewBox="0 0 24 24" width="18" height="18" fill="currentColor" style="display:none;"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
            </button>

            <button type="button" class="quicklook-vctrl-btn" id="ql-video-skip-back" title="${escapeHtml(t('video.skip_back', 'Rewind 10s'))} (J / ←)">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
                <path d="M3 3v5h5"/>
                <text x="12" y="15.5" font-size="8.5" font-family="sans-serif" font-weight="bold" fill="currentColor" text-anchor="middle" stroke="none">10</text>
              </svg>
            </button>

            <button type="button" class="quicklook-vctrl-btn" id="ql-video-skip-forward" title="${escapeHtml(t('video.skip_forward', 'Forward 10s'))} (L / →)">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 12a9 9 0 1 1-9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>
                <path d="M21 3v5h-5"/>
                <text x="12" y="15.5" font-size="8.5" font-family="sans-serif" font-weight="bold" fill="currentColor" text-anchor="middle" stroke="none">10</text>
              </svg>
            </button>

            <!-- Volume Container -->
            <div class="quicklook-video-vol-container">
              <button type="button" class="quicklook-vctrl-btn" id="ql-video-vol-btn" title="${escapeHtml(t('video.mute', 'Mute'))} (M)">
                <svg id="ql-icon-vol-high" viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
                <svg id="ql-icon-vol-muted" viewBox="0 0 24 24" width="18" height="18" fill="currentColor" style="display:none;"><path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/></svg>
              </button>
              <input type="range" class="quicklook-video-vol-slider" id="ql-video-vol-slider" min="0" max="1" step="0.05" value="1" aria-label="${escapeHtml(t('video.mute', 'Volume'))}">
            </div>

            <span class="quicklook-video-time" id="ql-video-time">00:00 / 00:00</span>
          </div>

          <!-- Right Controls -->
          <div class="quicklook-video-ctrl-group">
            <button type="button" class="quicklook-vctrl-pill" id="ql-video-speed-btn" title="${escapeHtml(t('video.speed', 'Playback Speed'))}">1x</button>
            <button type="button" class="quicklook-vctrl-btn" id="ql-video-loop-btn" title="${escapeHtml(t('video.loop', 'Loop'))}" aria-label="${escapeHtml(t('video.loop', 'Loop'))}">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/></svg>
            </button>
            ${isPipSupported ? `
            <button type="button" class="quicklook-vctrl-btn" id="ql-video-pip-btn" title="${escapeHtml(t('video.pip', 'Picture in Picture'))} (P)">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="14" x="3" y="5" rx="2"/><rect width="7" height="5" x="12" y="12" rx="1"/></svg>
            </button>` : ''}
            <button type="button" class="quicklook-vctrl-btn" id="ql-video-fs-btn" title="${escapeHtml(t('video.fullscreen', 'Fullscreen'))} (F)">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  `;

  const videoEl = container.querySelector('#quicklook-video-player');
  const containerEl = container.querySelector('#quicklook-video-container');
  const badgeEl = container.querySelector('#ql-video-badge');
  const centerBtn = container.querySelector('#ql-video-center-btn');
  const playBtn = container.querySelector('#ql-video-play-btn');
  const playIcon = playBtn?.querySelector('.ql-icon-play');
  const pauseIcon = playBtn?.querySelector('.ql-icon-pause');
  const skipBackBtn = container.querySelector('#ql-video-skip-back');
  const skipFwdBtn = container.querySelector('#ql-video-skip-forward');
  const volBtn = container.querySelector('#ql-video-vol-btn');
  const volHighIcon = container.querySelector('#ql-icon-vol-high');
  const volMutedIcon = container.querySelector('#ql-icon-vol-muted');
  const volSlider = container.querySelector('#ql-video-vol-slider');
  const timeEl = container.querySelector('#ql-video-time');
  const speedBtn = container.querySelector('#ql-video-speed-btn');
  const loopBtn = container.querySelector('#ql-video-loop-btn');
  const pipBtn = container.querySelector('#ql-video-pip-btn');
  const fsBtn = container.querySelector('#ql-video-fs-btn');

  const scrubContainer = container.querySelector('#ql-video-scrub-container');
  const progressBar = container.querySelector('#ql-video-progress-bar');
  const bufferBar = container.querySelector('#ql-video-buffer-bar');
  const thumbEl = container.querySelector('#ql-video-scrub-thumb');
  const tooltipEl = container.querySelector('#ql-video-time-tooltip');

  let badgeTimer = null;
  function showBadge(text, ms = 850) {
    if (!badgeEl) return;
    badgeEl.textContent = text;
    badgeEl.classList.add('show');
    clearTimeout(badgeTimer);
    badgeTimer = setTimeout(() => {
      badgeEl?.classList.remove('show');
    }, ms);
  }

  const videoPath = _currentPath;
  if (videoEl) {
    videoEl.addEventListener('loadedmetadata', () => {
      const at = getResume(videoPath, videoEl.duration);
      if (at) {
        videoEl.currentTime = at;
        const mm = Math.floor(at / 60);
        const ss = String(Math.floor(at % 60)).padStart(2, '0');
        showBadge(t('video.resumed', 'Continuing at {time}', { time: `${mm}:${ss}` }), 2500);
      }
    }, { once: true });
    let lastSaved = 0;
    videoEl.addEventListener('timeupdate', () => {
      if (Math.abs(videoEl.currentTime - lastSaved) >= 5) {
        lastSaved = videoEl.currentTime;
        setResume(videoPath, videoEl.currentTime, videoEl.duration);
      }
    });
    videoEl.addEventListener('ended', () => setResume(videoPath, 0, videoEl.duration));
    videoEl.addEventListener('error', () => showUnplayableVideo(container, meta));
    addSubtitles(videoEl, videoPath);
  }

  let hudTimer = null;
  function resetHudTimer() {
    containerEl?.classList.remove('hud-hidden');
    clearTimeout(hudTimer);
    if (videoEl && !videoEl.paused) {
      hudTimer = setTimeout(() => {
        if (videoEl && !videoEl.paused) {
          containerEl?.classList.add('hud-hidden');
        }
      }, 2500);
    }
  }

  function formatMediaTime(s) {
    if (isNaN(s) || s < 0) s = 0;
    const sec = Math.floor(s % 60);
    const min = Math.floor((s / 60) % 60);
    const hrs = Math.floor(s / 3600);
    const pad = (n) => String(n).padStart(2, '0');
    if (hrs > 0) return `${hrs}:${pad(min)}:${pad(sec)}`;
    return `${pad(min)}:${pad(sec)}`;
  }

  function updatePlayState(isPlaying) {
    containerEl?.classList.toggle('is-playing', isPlaying);
    if (playIcon) playIcon.style.display = isPlaying ? 'none' : 'block';
    if (pauseIcon) pauseIcon.style.display = isPlaying ? 'block' : 'none';
    if (playBtn) playBtn.title = isPlaying ? `${t('video.pause', 'Pause')} (Space / K)` : `${t('video.play', 'Play')} (Space / K)`;
    if (isPlaying) {
      resetHudTimer();
    } else {
      containerEl?.classList.remove('hud-hidden');
    }
  }

  function togglePlayPause() {
    if (!videoEl) return;
    if (videoEl.paused) {
      if (typeof videoEl.play === 'function') {
        try {
          const prom = videoEl.play();
          if (prom && typeof prom.catch === 'function') prom.catch(() => {});
        } catch (_) {}
      }
    } else {
      if (typeof videoEl.pause === 'function') {
        try {
          videoEl.pause();
        } catch (_) {}
      }
    }
  }

  function updateVolIcons() {
    const isMuted = videoEl.muted || videoEl.volume === 0;
    if (volHighIcon) volHighIcon.style.display = isMuted ? 'none' : 'block';
    if (volMutedIcon) volMutedIcon.style.display = isMuted ? 'block' : 'none';
    if (volBtn) volBtn.title = isMuted ? `${t('video.unmute', 'Unmute')} (M)` : `${t('video.mute', 'Mute')} (M)`;
  }

  function seekDelta(seconds) {
    if (!videoEl) return;
    const target = Math.max(0, Math.min(videoEl.duration || 0, videoEl.currentTime + seconds));
    videoEl.currentTime = target;
    showBadge(seconds > 0 ? `↻ +${seconds}s` : `↺ ${seconds}s`);
    resetHudTimer();
  }

  function seekPercent(pct) {
    if (!videoEl || !videoEl.duration) return;
    videoEl.currentTime = Math.max(0, Math.min(videoEl.duration, pct * videoEl.duration));
    showBadge(`${Math.round(pct * 100)}%`);
    resetHudTimer();
  }

  function setVolumeDelta(delta) {
    if (!videoEl) return;
    const newVol = Math.max(0, Math.min(1, Math.round((videoEl.volume + delta) * 100) / 100));
    videoEl.volume = newVol;
    if (newVol > 0 && videoEl.muted) videoEl.muted = false;
    if (volSlider) volSlider.value = newVol;
    updateVolIcons();
    showBadge(videoEl.muted ? '🔇 Muted' : `🔊 ${Math.round(newVol * 100)}%`);
    resetHudTimer();
  }

  function toggleMute() {
    if (!videoEl) return;
    videoEl.muted = !videoEl.muted;
    if (!videoEl.muted && videoEl.volume === 0) {
      videoEl.volume = 0.5;
      if (volSlider) volSlider.value = 0.5;
    }
    updateVolIcons();
    showBadge(videoEl.muted ? '🔇 Muted' : `🔊 ${Math.round(videoEl.volume * 100)}%`);
    resetHudTimer();
  }

  const SPEEDS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0];
  function stepSpeed(direction = 1) {
    if (!videoEl) return;
    const curRate = videoEl.playbackRate;
    let idx = SPEEDS.findIndex((s) => Math.abs(s - curRate) < 0.05);
    if (idx === -1) idx = 2; // 1.0
    idx = (idx + direction + SPEEDS.length) % SPEEDS.length;
    videoEl.playbackRate = SPEEDS[idx];
    if (speedBtn) speedBtn.textContent = `${SPEEDS[idx]}x`;
    showBadge(`⚡ ${SPEEDS[idx]}x`);
    resetHudTimer();
  }

  function toggleLoop() {
    if (!videoEl) return;
    videoEl.loop = !videoEl.loop;
    loopBtn?.classList.toggle('active', videoEl.loop);
    showBadge(videoEl.loop ? '🔁 Loop On' : '➡️ Loop Off');
    resetHudTimer();
  }

  async function togglePip() {
    if (!videoEl) return;
    try {
      if (document.pictureInPictureElement) {
        await document.exitPictureInPicture();
      } else if (typeof videoEl.requestPictureInPicture === 'function') {
        await videoEl.requestPictureInPicture();
      }
    } catch (_) {}
  }

  // Scrubber events
  let isDraggingScrub = false;
  function seekFromEvent(e) {
    if (!videoEl || !videoEl.duration || !scrubContainer) return;
    const rect = scrubContainer.getBoundingClientRect();
    const clientX = e.clientX ?? (e.touches && e.touches[0]?.clientX) ?? 0;
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    videoEl.currentTime = ratio * videoEl.duration;
    if (progressBar) progressBar.style.width = `${ratio * 100}%`;
    if (thumbEl) thumbEl.style.left = `${ratio * 100}%`;
  }

  scrubContainer?.addEventListener('pointerdown', (e) => {
    isDraggingScrub = true;
    scrubContainer.classList.add('is-dragging');
    seekFromEvent(e);

    const onMove = (moveEv) => {
      if (isDraggingScrub) seekFromEvent(moveEv);
    };
    const onUp = () => {
      isDraggingScrub = false;
      scrubContainer?.classList.remove('is-dragging');
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  });

  scrubContainer?.addEventListener('pointermove', (e) => {
    if (!scrubContainer || !tooltipEl) return;
    const rect = scrubContainer.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    tooltipEl.style.left = `${ratio * 100}%`;
    if (videoEl?.duration) {
      tooltipEl.textContent = formatMediaTime(ratio * videoEl.duration);
    }
  });

  // Video element event listeners
  videoEl?.addEventListener('play', () => updatePlayState(true));
  videoEl?.addEventListener('pause', () => updatePlayState(false));
  videoEl?.addEventListener('ended', () => updatePlayState(false));

  videoEl?.addEventListener('timeupdate', () => {
    if (!isDraggingScrub && videoEl.duration) {
      const pct = (videoEl.currentTime / videoEl.duration) * 100;
      if (progressBar) progressBar.style.width = `${pct}%`;
      if (thumbEl) thumbEl.style.left = `${pct}%`;
    }
    if (timeEl) {
      timeEl.textContent = `${formatMediaTime(videoEl.currentTime)} / ${formatMediaTime(videoEl.duration || 0)}`;
    }
  });

  videoEl?.addEventListener('progress', () => {
    if (videoEl.duration && videoEl.buffered && videoEl.buffered.length > 0 && bufferBar) {
      const end = videoEl.buffered.end(videoEl.buffered.length - 1);
      bufferBar.style.width = `${(end / videoEl.duration) * 100}%`;
    }
  });

  videoEl?.addEventListener('loadedmetadata', () => {
    if (timeEl) {
      timeEl.textContent = `${formatMediaTime(videoEl.currentTime)} / ${formatMediaTime(videoEl.duration || 0)}`;
    }
  });

  // Controls button bindings
  centerBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    togglePlayPause();
  });
  playBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    togglePlayPause();
  });
  skipBackBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    seekDelta(-10);
  });
  skipFwdBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    seekDelta(10);
  });
  volBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleMute();
  });
  volSlider?.addEventListener('input', (e) => {
    if (!videoEl) return;
    const v = parseFloat(e.target.value);
    videoEl.volume = v;
    if (v > 0 && videoEl.muted) videoEl.muted = false;
    updateVolIcons();
  });
  speedBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    stepSpeed(1);
  });
  loopBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleLoop();
  });
  pipBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    togglePip();
  });
  fsBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleMaximize();
  });

  // Direct video interactions
  videoEl?.addEventListener('click', () => togglePlayPause());
  videoEl?.addEventListener('dblclick', (e) => {
    e.preventDefault();
    toggleMaximize();
  });

  // Mouse activity HUD auto-hide
  containerEl?.addEventListener('mousemove', () => resetHudTimer());
  containerEl?.addEventListener('mouseenter', () => resetHudTimer());
  containerEl?.addEventListener('mouseleave', () => {
    if (videoEl && !videoEl.paused) containerEl?.classList.add('hud-hidden');
  });

  // Store active controller reference
  _activeVideoController = {
    videoEl,
    togglePlayPause,
    seekDelta,
    seekPercent,
    setVolumeDelta,
    toggleMute,
    stepSpeed,
    toggleLoop,
    togglePip,
  };

  // Attempt autoplay safely
  if (videoEl && typeof videoEl.play === 'function') {
    try {
      const prom = videoEl.play();
      if (prom && typeof prom.catch === 'function') prom.catch(() => {});
    } catch (_) {}
  }
}

function showUnplayableVideo(container, meta) {
  const ext = (meta && meta.ext ? meta.ext : '').replace('.', '').toUpperCase();
  container.innerHTML = `
    <div class="quicklook-unplayable" role="alert">
      <div class="quicklook-unplayable-title">${escapeHtml(t('video.unplayable', "This video can't play in the browser"))}</div>
      <div class="quicklook-unplayable-text">${escapeHtml(t('video.unplayable_hint', 'Its format or codec ({ext}) isn\'t supported here. Download it, or open it in VLC or Infuse.', { ext: ext || '?' }))}</div>
      <button type="button" class="btn-pill-toggle" id="ql-unplayable-download">${ICONS.download} ${escapeHtml(t('preview.download', 'Download'))}</button>
    </div>`;
  container.querySelector('#ql-unplayable-download')?.addEventListener('click', () => triggerDownload());
  addGalleryNav(container);
}

const _folderCache = new Map();

/** Subtitles next to the video: movie.vtt, movie.srt, movie.en.srt … (shown when found). */
async function addSubtitles(videoEl, path) {
  const dir = path.slice(0, path.lastIndexOf('/')) || '/';
  const base = path.slice(path.lastIndexOf('/') + 1).replace(/\.[^.]+$/, '');
  try {
    if (!_folderCache.has(dir)) {
      const res = await api.get(`/api/browse?path=${encodeURIComponent(dir)}&dirs_only=0`);
      _folderCache.set(dir, (res.dirs || []).filter((f) => !f.is_dir).map((f) => f.name));
      if (_folderCache.size > 20) _folderCache.delete(_folderCache.keys().next().value);
    }
    const names = _folderCache.get(dir) || [];
    const subs = names.filter((n) => n.startsWith(base + '.') && /\.(vtt|srt)$/i.test(n)).slice(0, 4);
    for (const name of subs) {
      const r = await fetch(`/api/fs/download?path=${encodeURIComponent(`${dir}/${name}`)}`, { credentials: 'same-origin' });
      if (!r.ok) continue;
      const text = await r.text();
      const vtt = /\.srt$/i.test(name) ? srtToVtt(text) : text;
      const track = document.createElement('track');
      track.kind = 'subtitles';
      const lang = name.slice(base.length + 1).replace(/\.(vtt|srt)$/i, '');
      track.label = lang || t('video.subtitles', 'Subtitles');
      if (/^[a-z]{2,3}$/i.test(lang)) track.srclang = lang.toLowerCase();
      track.src = URL.createObjectURL(new Blob([vtt], { type: 'text/vtt' }));
      if (!videoEl.querySelector('track')) track.default = true;
      videoEl.appendChild(track);
    }
  } catch (_) {
    // no subtitles: the video still plays
  }
}

export function closeFilePreviewModal() {
  if (_activeVideoController) {
    if (_activeVideoController.videoEl && !_activeVideoController.videoEl.paused) {
      try {
        _activeVideoController.videoEl.pause();
      } catch (_) {}
    }
    _activeVideoController = null;
  }
  if (_previewKeydownListener) {
    window.removeEventListener('keydown', _previewKeydownListener);
    _previewKeydownListener = null;
  }
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
  return formatBytes(bytes, { decimals: 2 });
}

window.openFilePreviewModal = openFilePreviewModal;
window.closeFilePreviewModal = closeFilePreviewModal;
