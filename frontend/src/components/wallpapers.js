import { state } from '../state.js';
/**
 * ZettNAS Toolkit Custom Wallpaper Engine
 * Handles wallpaper uploading, gallery dropdown, renaming, and desktop styling.
 */
import { api } from '../api.js';
import { showToast } from '../toast.js';

export function initWallpapers() {
  const fileInput = document.getElementById('wallpaper-upload');
  const clearBtn = document.getElementById('wallpaper-clear-btn');
  const previewImg = document.getElementById('wallpaper-preview');
  const noImgTxt = document.getElementById('wallpaper-no-img');
  const selectDropdown = document.getElementById('wallpaper-select');
  const deleteBtn = document.getElementById('wallpaper-delete-btn');
  const renameBtn = document.getElementById('wallpaper-rename-btn');

  let currentWallpapers = [];

  function setWallpaper(url) {
    if (state.isLcdDirect || (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) || (document.body && document.body.classList.contains('lcd-direct'))) return;
    if (url) {
      document.body.style.backgroundImage = `url('${url}')`;
      document.body.style.backgroundSize = 'cover';
      document.body.style.backgroundPosition = 'center';
      document.body.style.backgroundRepeat = 'no-repeat';
      document.body.style.backgroundAttachment = 'fixed';
      if (previewImg) {
        previewImg.src = url;
        previewImg.style.display = 'block';
      }
      if (noImgTxt) noImgTxt.style.display = 'none';
    } else {
      document.body.style.backgroundImage = '';
      document.body.style.backgroundSize = '';
      document.body.style.backgroundPosition = '';
      document.body.style.backgroundRepeat = '';
      document.body.style.backgroundAttachment = '';
      if (previewImg) {
        previewImg.src = '';
        previewImg.style.display = 'none';
      }
      if (noImgTxt) noImgTxt.style.display = 'block';
    }
  }

  async function loadWallpapers() {
    try {
      const data = await api.get('/api/wallpapers');
      currentWallpapers = data.files || [];

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
          setWallpaper(`/api/wallpapers/download/${data.active}?t=${Date.now()}`);
        } else {
          selectDropdown.value = '';
          setWallpaper(null);
        }
      }
    } catch (err) {
      console.warn('Could not load wallpapers', err);
    }
  }

  loadWallpapers();

  if (selectDropdown) {
    selectDropdown.addEventListener('change', (e) => {
      const val = e.target.value;
      if (val) {
        setWallpaper(`/api/wallpapers/download/${val}`);
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
        showToast('Wallpaper deleted', 'success');
        await loadWallpapers();
      } catch (err) {
        showToast('Delete failed: ' + err.message, 'error');
      }
    });
  }
}
