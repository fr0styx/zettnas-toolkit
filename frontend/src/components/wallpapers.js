import { state } from '../state.js';
/**
 * ZettNAS Toolkit Custom Wallpaper Engine
 * Handles wallpaper uploading, gallery dropdown, renaming, and desktop styling.
 */
import { api } from '../api.js';
import { showToast } from '../toast.js';

let _wallpapersInitialized = false;
let _loadPromise = null;

export function setWallpaper(url, filename = null) {
  if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
  const previewImg = document.getElementById('wallpaper-preview');
  const noImgTxt = document.getElementById('wallpaper-no-img');

  if (url) {
    if (filename) {
      try {
        localStorage.setItem('zettnas_active_wallpaper', filename);
      } catch (e) {}
    }
    document.body.style.setProperty('background-image', `url('${url}')`, 'important');
    document.body.style.setProperty('background-size', 'cover', 'important');
    document.body.style.setProperty('background-position', 'center center', 'important');
    document.body.style.setProperty('background-repeat', 'no-repeat', 'important');
    document.body.style.setProperty('background-attachment', 'fixed', 'important');
    if (previewImg) {
      previewImg.src = url;
      previewImg.style.display = 'block';
    }
    if (noImgTxt) noImgTxt.style.display = 'none';
  } else {
    try {
      localStorage.removeItem('zettnas_active_wallpaper');
    } catch (e) {}
    document.body.style.removeProperty('background-image');
    document.body.style.removeProperty('background-size');
    document.body.style.removeProperty('background-position');
    document.body.style.removeProperty('background-repeat');
    document.body.style.removeProperty('background-attachment');
    if (previewImg) {
      previewImg.src = '';
      previewImg.style.display = 'none';
    }
    if (noImgTxt) noImgTxt.style.display = 'block';
  }

  const earlyWp = document.getElementById('zettnas-wallpaper-early-style');
  if (earlyWp && earlyWp.parentNode) {
    earlyWp.parentNode.removeChild(earlyWp);
  }
}

export function loadWallpapers() {
  if (_loadPromise) return _loadPromise;
  _loadPromise = (async () => {
    try {
      const data = await api.get('/api/wallpapers');
      const currentWallpapers = data.files || [];
      const selectDropdown = document.getElementById('wallpaper-select');

      if (selectDropdown) {
        selectDropdown.innerHTML = '<option value="">Default Gradient</option>';
        currentWallpapers.forEach((f) => {
          const opt = document.createElement('option');
          opt.value = f;
          opt.textContent = f;
          selectDropdown.appendChild(opt);
        });
        if (data.active) {
          selectDropdown.value = data.active;
          const v = data.version ? `?v=${data.version}` : '';
          setWallpaper(`/api/wallpapers/download/${encodeURIComponent(data.active)}${v}`, data.active);
        } else {
          selectDropdown.value = '';
          setWallpaper(null);
        }
      } else if (data.active) {
        const v = data.version ? `?v=${data.version}` : '';
        setWallpaper(`/api/wallpapers/download/${encodeURIComponent(data.active)}${v}`, data.active);
      } else {
        setWallpaper(null);
      }
    } catch (err) {
      console.warn('Could not load wallpapers', err);
    }
  })().finally(() => {
    _loadPromise = null;
  });
  return _loadPromise;
}

if (typeof window !== 'undefined') {
  window.loadWallpapers = loadWallpapers;
  window.setWallpaper = setWallpaper;
}

export function initWallpapers() {
  const fileInput = document.getElementById('wallpaper-upload');
  const clearBtn = document.getElementById('wallpaper-clear-btn');
  const selectDropdown = document.getElementById('wallpaper-select');
  const deleteBtn = document.getElementById('wallpaper-delete-btn');
  const renameBtn = document.getElementById('wallpaper-rename-btn');

  loadWallpapers();

  if (_wallpapersInitialized) return;
  _wallpapersInitialized = true;

  if (selectDropdown) {
    selectDropdown.addEventListener('change', (e) => {
      const val = e.target.value;
      if (val) {
        setWallpaper(`/api/wallpapers/download/${encodeURIComponent(val)}`, val);
      } else {
        setWallpaper(null);
      }
    });
  }

  if (fileInput) {
    fileInput.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = async (ev) => {
        const base64data = ev.target.result;
        try {
          const data = await api.post('/api/wallpapers/upload', {
            image: base64data,
            filename: file.name
          });
          if (data.success) {
            if (data.filename) {
              try {
                localStorage.setItem('zettnas_active_wallpaper', data.filename);
              } catch (e) {}
            }
            await loadWallpapers();
            showToast('Wallpaper uploaded', 'success');
          } else {
            showToast('Failed: ' + (data.error || 'Upload error'), 'error');
          }
        } catch (err) {
          showToast('Upload failed: ' + err.message, 'error');
        }
      };
      reader.readAsDataURL(file);
      fileInput.value = '';
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', async () => {
      const val = selectDropdown ? selectDropdown.value : '';
      try {
        await api.post('/api/wallpapers/select', { filename: val || null });
        if (val) {
          try {
            localStorage.setItem('zettnas_active_wallpaper', val);
          } catch (e) {}
        } else {
          try {
            localStorage.removeItem('zettnas_active_wallpaper');
          } catch (e) {}
        }
        showToast('Active wallpaper saved', 'success');
      } catch (err) {
        showToast('Failed to save wallpaper setting', 'error');
      }
    });
  }

  if (renameBtn) {
    renameBtn.addEventListener('click', async () => {
      const val = selectDropdown ? selectDropdown.value : '';
      if (!val) return;

      const newName = prompt(`Enter new name for ${val}:`, val);
      if (!newName || newName === val) return;

      try {
        const data = await api.post('/api/wallpapers/rename', {
          old_name: val,
          new_name: newName
        });
        if (data.success) {
          showToast(`Wallpaper renamed to ${data.new_name}`, 'success');
          if (localStorage.getItem('zettnas_active_wallpaper') === val) {
            try {
              localStorage.setItem('zettnas_active_wallpaper', data.new_name);
            } catch (e) {}
          }
          await loadWallpapers();
          if (selectDropdown) selectDropdown.value = data.new_name;
        } else {
          showToast('Rename failed: ' + (data.error || 'Unknown error'), 'error');
        }
      } catch (err) {
        showToast('Rename request failed: ' + err.message, 'error');
      }
    });
  }

  if (deleteBtn) {
    deleteBtn.addEventListener('click', async () => {
      const val = selectDropdown ? selectDropdown.value : '';
      if (!val) return;
      try {
        await api.delete(`/api/wallpapers/${encodeURIComponent(val)}`);
        if (localStorage.getItem('zettnas_active_wallpaper') === val) {
          try {
            localStorage.removeItem('zettnas_active_wallpaper');
          } catch (e) {}
        }
        showToast('Wallpaper deleted', 'success');
        await loadWallpapers();
      } catch (err) {
        showToast('Delete failed: ' + err.message, 'error');
      }
    });
  }
}
