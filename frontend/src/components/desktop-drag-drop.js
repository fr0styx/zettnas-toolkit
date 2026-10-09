/**
 * ZettNAS Toolkit - Desktop Wallpaper Drag & Drop Ingestion
 * Allows users to drag any image file from their OS desktop / file explorer
 * and drop it anywhere on the ZettNAS desktop to immediately upload and set as wallpaper.
 */
import { uploadAndApplyWallpaper } from './wallpapers.js';
import { showToast } from '../toast.js';

let _dragDropInitialized = false;
let _dragCounter = 0;

export function initDesktopDragAndDrop() {
  if (_dragDropInitialized) return;
  _dragDropInitialized = true;

  const dropZone = document.getElementById('desktop-drop-zone');
  if (!dropZone) return;

  const hasFiles = (e) => {
    return e.dataTransfer && e.dataTransfer.types && (
      e.dataTransfer.types.includes('Files') ||
      Array.from(e.dataTransfer.types).includes('Files')
    );
  };

  window.addEventListener('dragenter', (e) => {
    if (!hasFiles(e)) return;
    _dragCounter++;
    if (_dragCounter === 1) {
      dropZone.style.display = 'flex';
      dropZone.classList.add('active');
      dropZone.setAttribute('aria-hidden', 'false');
    }
  });

  window.addEventListener('dragover', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  });

  window.addEventListener('dragleave', (e) => {
    if (!hasFiles(e)) return;
    _dragCounter = Math.max(0, _dragCounter - 1);
    if (_dragCounter === 0) {
      hideDropZone();
    }
  });

  window.addEventListener('drop', async (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    _dragCounter = 0;
    hideDropZone();

    const files = e.dataTransfer.files;
    if (!files || !files.length) return;

    // Search for first valid image file
    let imageFile = null;
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      if (f.type.startsWith('image/') || /\.(png|jpe?g|webp|gif|avif)$/i.test(f.name)) {
        imageFile = f;
        break;
      }
    }

    if (!imageFile) {
      showToast('Please drop an image file (.jpg, .png, .webp)', 'warn');
      return;
    }

    // Limit size to 16MB
    const MAX_BYTES = 16 * 1024 * 1024;
    if (imageFile.size > MAX_BYTES) {
      showToast('Image file exceeds 16MB limit', 'error');
      return;
    }

    showToast(`Uploading wallpaper: ${imageFile.name}...`, 'info');
    try {
      await uploadAndApplyWallpaper(imageFile);
    } catch (err) {
      console.error('[DESKTOP DND] Failed uploading wallpaper:', err);
    }
  });
}

export function hideDropZone() {
  const dropZone = document.getElementById('desktop-drop-zone');
  if (dropZone) {
    dropZone.classList.remove('active');
    dropZone.style.display = 'none';
    dropZone.setAttribute('aria-hidden', 'true');
  }
}
