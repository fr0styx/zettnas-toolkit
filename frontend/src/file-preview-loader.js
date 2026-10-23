/**
 * The file viewer (~160 kB) loads the first time a file is opened, not with the page (PERF-5).
 * Until then window.openFilePreviewModal is a stub that loads it; the module replaces the
 * stub with the real function when it loads.
 */
let _loading = null;

export function loadFilePreview() {
  if (!_loading) {
    _loading = import('./components/file-preview-modal.js');
    _loading.catch(() => {
      _loading = null; // allow a retry, e.g. after a network blip
    });
  }
  return _loading;
}

export function openFilePreview(...args) {
  return loadFilePreview().then((m) => m.openFilePreviewModal(...args));
}

if (typeof window !== 'undefined' && typeof window.openFilePreviewModal !== 'function') {
  window.openFilePreviewModal = (...args) => openFilePreview(...args);
}
