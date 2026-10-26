// Installer images: the official catalog, downloads and uploads.
// Part of vm-manager.js, split out by ARC-5.

import { api } from '../../api.js';
import { escapeHtml, trapFocus } from '../../utils.js';
import { showToast, showConfirmToast } from '../../toast.js';
import { t } from '../../i18n.js';
import { makeDraggable, bringToFront } from '../dock.js';
import { vmState } from './state.js';
import { openVmCreateModal } from './create-modal.js';
import { loadVmDashboard } from '../vm-manager.js';

/**
 * Official OS Catalog Data Definition
 */
export const OFFICIAL_ISO_CATALOG = [
  {
    id: 'ubuntu-2404',
    name: 'Ubuntu Server 24.04.1 LTS',
    family: 'linux',
    badge: 'Official Canonical',
    edition: 'Noble Numbat',
    size_formatted: '2.6 GB',
    arch: 'x86_64',
    kernel: 'Linux 6.8',
    url: 'https://releases.ubuntu.com/24.04.1/ubuntu-24.04.1-live-server-amd64.iso',
    filename: 'ubuntu-24.04.1-live-server-amd64.iso',
    desc: 'Enterprise grade cloud & container host. Pre-configured with cloud-init and OpenSSH.'
  },
  {
    id: 'debian-12',
    name: 'Debian 12.7.0 (Bookworm) Netinst',
    family: 'linux',
    badge: 'Stable Minimal',
    edition: 'Netinst Minimal',
    size_formatted: '630 MB',
    arch: 'x86_64',
    kernel: 'Linux 6.1 LTS',
    url: 'https://cdimage.debian.org/cdimage/archive/12.7.0/amd64/iso-cd/debian-12.7.0-amd64-netinst.iso',
    filename: 'debian-12.7.0-amd64-netinst.iso',
    desc: 'The universal operating system. Ultra-light memory footprint, rock solid package ecosystem.'
  },
  {
    id: 'alpine-320',
    name: 'Alpine Linux 3.20.3',
    family: 'linux',
    badge: 'Micro Hypervisor',
    edition: 'Standard Edition',
    size_formatted: '209 MB',
    arch: 'x86_64',
    kernel: 'Linux 6.6 LTS',
    url: 'https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/alpine-standard-3.20.3-x86_64.iso',
    filename: 'alpine-standard-3.20.3-x86_64.iso',
    desc: 'Musl libc and BusyBox based ultra-lean OS. Boots in 400ms, uses under 32MB host RAM.'
  },
  {
    id: 'fedora-40',
    name: 'Fedora Server 40',
    family: 'linux',
    badge: 'Modern Enterprise',
    edition: 'Server Netinstall',
    size_formatted: '2.5 GB',
    arch: 'x86_64',
    kernel: 'Linux 6.8',
    url: 'https://download.fedoraproject.org/pub/fedora/linux/releases/40/Server/x86_64/iso/Fedora-Server-dvd-x86_64-40-1.14.iso',
    filename: 'Fedora-Server-dvd-x86_64-40-1.14.iso',
    desc: 'Leading-edge Linux platform with native systemd-nspawn, Podman, and Cockpit integration.'
  },
  {
    id: 'truenas-scale',
    name: 'TrueNAS SCALE 24.04.2',
    family: 'storage',
    badge: 'Scale-Out NAS',
    edition: 'Dragonfish',
    size_formatted: '1.7 GB',
    arch: 'x86_64',
    kernel: 'Linux 6.6 LTS',
    url: 'https://download.sys.truenas.net/TrueNAS-SCALE-Dragonfish/24.04.2/TrueNAS-SCALE-24.04.2.iso',
    filename: 'TrueNAS-SCALE-24.04.2.iso',
    desc: 'Debian-based open hyper-converged scale-out storage, ZFS pools, and containerized apps.'
  },
  {
    id: 'virtio-win',
    name: 'VirtIO Windows Guest Tools',
    family: 'windows',
    badge: 'KVM Drivers',
    edition: 'Stable 0.1.262',
    size_formatted: '650 MB',
    arch: 'x86_64 / x86',
    kernel: 'WHQL Signed',
    url: 'https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso',
    filename: 'virtio-win-stable.iso',
    desc: 'Essential Red Hat signed VirtIO storage (viostor), network (NetKVM), and memory balloon drivers.'
  },
  {
    id: 'win-server-2022',
    name: 'Windows Server 2022 Eval',
    family: 'windows',
    badge: 'Microsoft Eval',
    edition: 'Standard / Datacenter',
    size_formatted: '4.7 GB',
    arch: 'x86_64',
    kernel: 'NT 10.0',
    url: 'https://software-download.microsoft.com/download/pr/SERVER_EVAL_x64FRE_en-us.iso',
    filename: 'Windows_Server_2022_Eval_x64.iso',
    desc: 'Official Microsoft 180-day evaluation image for Active Directory and Windows workloads.'
  }
];

let _isoPollTimers = {};

/**
 * Opens ISO Management Modal (#modal-iso-manager) as an independent Desktop OS Window
 */
export async function openIsoManagerModal(initialTab = 'catalog') {
  let modal = document.getElementById('modal-iso-manager');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'modal-iso-manager';
    modal.className = 'os-window vm-iso-window';
    modal.style.cssText = 'display: none; width: 860px; height: 620px; min-width: 600px; min-height: 440px;';

    const left = Math.max(30, Math.floor((window.innerWidth - 860) / 2) + 20);
    const top = Math.max(40, Math.floor((window.innerHeight - 620) / 2) + 25);
    modal.style.left = `${left}px`;
    modal.style.top = `${top}px`;

    modal.innerHTML = `
      <div class="os-window-header" id="iso-win-header" style="cursor: move;">
        <div class="os-window-title" style="display: flex; align-items: center; gap: 8px;">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><line x1="12" y1="2" x2="12" y2="5"/></svg>
          <span>ISO Storage & Official OS Catalog</span>
        </div>
        <div class="os-window-controls">
          <button class="win-btn min-btn" id="iso-win-min" title="${t('window.minimize', 'Minimize')}" aria-label="${t('window.minimize', 'Minimize')}"></button>
          <button class="win-btn max-btn" id="iso-win-max" title="${t('ui.maximize', 'Maximize')}" aria-label="${t('ui.maximize', 'Maximize')}"></button>
          <button class="win-btn close-btn" id="iso-modal-close" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
        </div>
      </div>

      <!-- Navigation Tabs -->
      <div class="iso-modal-tabs" style="display: flex; gap: 8px; padding: 10px 18px; background: var(--zn-shade-25); border-bottom: 1px solid var(--zn-line-6); flex-shrink: 0;">
        <button id="tab-btn-catalog" class="btn-pill-toggle active" style="flex: 1;">
          <span>🌐 Official ISO Catalog</span>
        </button>
        <button id="tab-btn-local" class="btn-pill-toggle" style="flex: 1;">
          <span>📁 Local Storage ISOs (/mnt/user/isos)</span>
        </button>
      </div>

      <div class="os-window-body" style="flex: 1; overflow-y: auto; padding: 18px 22px;">
        <!-- Tab 1: Official Catalog -->
        <div id="tab-content-catalog">
          <div style="font-size: var(--zn-fs-xs); color: var(--muted); margin-bottom: 14px;">
            Verified, turnkey operating system images ready for 1-click download directly to your storage pool (<code style="color: var(--zn-text-accent);">/mnt/user/isos</code>).
          </div>
          <div class="catalog-grid" id="catalog-grid-container" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px;">
            <!-- Rendered by renderCatalogCards() -->
          </div>
        </div>

        <!-- Tab 2: Local Storage ISOs & Drag-and-Drop Upload -->
        <div id="tab-content-local" style="display: none;">
          <!-- Dropzone -->
          <div id="iso-dropzone" class="iso-dropzone" style="border: 2px dashed rgba(14,165,233,0.4); border-radius: 8px; padding: 24px; text-align: center; background: rgba(14,165,233,0.03); cursor: pointer; transition: all 0.2s;">
            <div style="font-size: 28px; margin-bottom: 8px;">💿</div>
            <div style="font-weight: 700; color: var(--zn-text-strong); font-size: 13px;">Drag & Drop ISO files here to upload</div>
            <div style="font-size: var(--zn-fs-xs); color: var(--muted); margin-top: 4px;">Destination: <code style="color: var(--zn-text-accent);">/mnt/user/isos</code> • Supports .iso, .img up to 50 GB</div>
            <input type="file" id="iso-file-input" accept=".iso,.img" style="display: none;" />
            <button id="btn-browse-iso" class="btn-pill-toggle" style="margin-top: 12px;">Select ISO File...</button>
          </div>

          <!-- Upload Progress Card -->
          <div id="iso-upload-progress-card" style="display: none; margin-top: 14px; padding: 12px 14px; background: var(--zn-shade-30); border: 1px solid var(--zn-line-8); border-radius: 6px;">
            <div style="display: flex; justify-content: space-between; font-size: var(--zn-fs-xs); margin-bottom: 6px;">
              <span id="upload-filename" style="color: var(--zn-text-strong); font-weight: 600;">uploading.iso</span>
              <span id="upload-rate" style="color: var(--zn-text-accent);">0 MB/s</span>
            </div>
            <div style="height: 8px; border-radius: 4px; background: var(--zn-glaze-10); overflow: hidden;">
              <div id="upload-progress-bar" style="width: 0%; height: 100%; background: #10b981; transition: width 0.15s;"></div>
            </div>
          </div>

          <!-- Existing Local Files Table -->
          <div style="margin-top: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong);">Discovered Images in /mnt/user/isos</div>
              <button id="btn-refresh-local-isos" class="btn-pill-toggle is-small">↺ Refresh</button>
            </div>
            <div id="local-iso-list" style="display: flex; flex-direction: column; gap: 8px;"></div>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(modal);

    // Register with DockManager
    if (window.DockManager) {
      window.DockManager.register('vm-iso-manager', modal, '#i-vm', 'ISO Storage & Catalog');
    }

    makeDraggable(modal, modal.querySelector('#iso-win-header'));
    modal.addEventListener('mousedown', () => bringToFront(modal));

    // Minimize, Maximize, Close Bindings
    const minBtn = modal.querySelector('#iso-win-min');
    const maxBtn = modal.querySelector('#iso-win-max');
    const closeBtn = modal.querySelector('#iso-modal-close');

    if (minBtn) {
      minBtn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        if (modal._unbindTrap) {
          try { modal._unbindTrap(); } catch (_) {}
          modal._unbindTrap = null;
        }
        modal.classList.add('window-minimized');
        modal.classList.remove('open');
        modal.style.setProperty('display', 'none', 'important');
        if (window.DockManager) window.DockManager.minimize('vm-iso-manager');
      };
    }

    let isMax = false;
    let preBounds = null;
    if (maxBtn) {
      maxBtn.onclick = () => {
        if (!isMax) {
          preBounds = {
            left: modal.style.left,
            top: modal.style.top,
            width: modal.style.width,
            height: modal.style.height,
          };
          modal.style.left = '0px';
          modal.style.top = '36px';
          modal.style.width = '100vw';
          modal.style.height = 'calc(100vh - 36px - 72px)';
          isMax = true;
        } else {
          if (preBounds) {
            modal.style.left = preBounds.left;
            modal.style.top = preBounds.top;
            modal.style.width = preBounds.width;
            modal.style.height = preBounds.height;
          }
          isMax = false;
        }
      };
    }

    if (closeBtn) {
      closeBtn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        if (modal._unbindTrap) {
          try { modal._unbindTrap(); } catch (_) {}
          modal._unbindTrap = null;
        }
        modal.classList.add('window-minimized');
        modal.classList.remove('open');
        modal.style.setProperty('display', 'none', 'important');
        if (window.DockManager) window.DockManager.closeWindow('vm-iso-manager');
      };
    }

    // Drag and Drop Upload Event Listeners
    const dropzone = modal.querySelector('#iso-dropzone');
    const fileInput = modal.querySelector('#iso-file-input');
    const btnBrowse = modal.querySelector('#btn-browse-iso');

    if (btnBrowse && fileInput) {
      btnBrowse.onclick = () => fileInput.click();
      fileInput.onchange = (e) => {
        const file = e.target.files[0];
        if (file) handleUpload(file);
      };
    }

    if (dropzone) {
      dropzone.ondragover = (e) => {
        e.preventDefault();
        dropzone.style.borderColor = '#38bdf8';
        dropzone.style.background = 'rgba(14,165,233,0.1)';
      };
      dropzone.ondragleave = () => {
        dropzone.style.borderColor = 'rgba(14,165,233,0.4)';
        dropzone.style.background = 'rgba(14,165,233,0.03)';
      };
      dropzone.ondrop = (e) => {
        e.preventDefault();
        dropzone.style.borderColor = 'rgba(14,165,233,0.4)';
        dropzone.style.background = 'rgba(14,165,233,0.03)';
        const file = e.dataTransfer.files[0];
        if (file) handleUpload(file);
      };
    }

    modal.querySelector('#btn-refresh-local-isos')?.addEventListener('click', async () => {
      await loadVmDashboard();
      renderLocalIsoList();
      renderCatalogCards();
      showToast(t('toast.iso_list_refreshed', 'ISO list refreshed.'), 'info');
    });
  }

  // Real Streaming Upload Implementation
  function handleUpload(file) {
    if (!file) return;
    const progCard = modal.querySelector('#iso-upload-progress-card');
    const progBar = modal.querySelector('#upload-progress-bar');
    const progFilename = modal.querySelector('#upload-filename');
    const progRate = modal.querySelector('#upload-rate');

    if (progCard) progCard.style.display = 'block';
    if (progFilename) progFilename.textContent = file.name;
    if (progBar) progBar.style.width = '0%';
    if (progRate) progRate.textContent = t('ui.starting_upload', 'Starting upload...');

    const xhr = new XMLHttpRequest();
    let lastTime = Date.now();
    let lastLoaded = 0;

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        const now = Date.now();
        const dt = (now - lastTime) / 1000;
        if (dt >= 0.25) {
          const speed = (e.loaded - lastLoaded) / (1024 * 1024) / dt;
          lastTime = now;
          lastLoaded = e.loaded;
          if (progRate) progRate.textContent = `${speed.toFixed(1)} MB/s (${pct}%)`;
        }
        if (progBar) progBar.style.width = `${pct}%`;
      }
    };

    xhr.onload = async () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        if (progBar) progBar.style.width = '100%';
        if (progRate) progRate.textContent = t('ui.upload_complete', 'Upload Complete');
        showToast(t('toast.iso_uploaded_successfully_to_mnt_user', 'ISO \'{name}\' uploaded successfully to /mnt/user/isos', { name: file.name }), 'success');
        await loadVmDashboard();
        renderLocalIsoList();
        renderCatalogCards();
        document.getElementById('fm-refresh-btn')?.click();
      } else {
        let errDetail = 'Upload failed';
        try {
          const errObj = JSON.parse(xhr.responseText);
          if (errObj && errObj.detail) errDetail = errObj.detail;
        } catch (_) {}
        showToast(t('toast.upload_failed', 'Upload failed: {errDetail}', { errDetail: errDetail }), 'error');
        if (progRate) progRate.textContent = `Error: ${errDetail}`;
      }
    };

    xhr.onerror = () => {
      showToast(t('toast.network_error_while_uploading_iso', 'Network error while uploading ISO'), 'error');
      if (progRate) progRate.textContent = t('ui.network_error', 'Network Error');
    };

    xhr.open('POST', '/api/vms/isos/upload');
    xhr.setRequestHeader('x-filename', file.name);
    xhr.withCredentials = true;
    xhr.send(file);
  }

  // Populate or refresh local ISOs
  function renderLocalIsoList() {
    const localList = modal.querySelector('#local-iso-list');
    if (!localList) return;

    if (!vmState.isos || vmState.isos.length === 0) {
      localList.innerHTML = `<div style="font-size: var(--zn-fs-xs); color: var(--muted); padding: 12px 0;">No local ISO images discovered in /mnt/user/isos.</div>`;
    } else {
      localList.innerHTML = vmState.isos.map((iso) => `
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: var(--zn-glaze-3); border: 1px solid var(--zn-line-6); border-radius: 6px;">
          <div style="display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1;">
            <span style="font-size: 18px;">💿</span>
            <div style="min-width: 0; flex: 1;">
              <div style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-strong); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${escapeHtml(iso.name)}</div>
              <div style="font-size: var(--zn-fs-xs); color: var(--muted); font-family: monospace;">${escapeHtml(iso.path)}</div>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px; margin-left: 12px; flex-shrink: 0;">
            <span style="font-size: var(--zn-fs-xs); font-weight: 600; color: var(--zn-text-muted);">${iso.size_formatted}</span>
            <button class="btn-pill-toggle btn-boot-iso" data-path="${escapeHtml(iso.path)}" style="background: rgba(14,165,233,0.18); color: var(--zn-text-accent); border-color: rgba(14,165,233,0.35);">▶ Boot VM</button>
            <button class="btn-pill-toggle btn-delete-iso is-danger" data-path="${escapeHtml(iso.path)}" data-name="${escapeHtml(iso.name)}" title="${t('ui.delete_iso_from_storage', 'Delete ISO from storage')}">🗑</button>
          </div>
        </div>
      `).join('');

      localList.querySelectorAll('.btn-boot-iso').forEach((btn) => {
        btn.onclick = () => {
          const path = btn.dataset.path;
          if (window.DockManager) window.DockManager.minimize('vm-iso-manager');
          else modal.style.display = 'none';
          openVmCreateModal();
          const select = document.getElementById('vm-create-iso');
          if (select) select.value = path;
        };
      });

      localList.querySelectorAll('.btn-delete-iso').forEach((btn) => {
        btn.onclick = () => {
          const path = btn.dataset.path;
          const name = btn.dataset.name;
          showConfirmToast(
            t('vms.delete_iso_title', 'Delete ISO Image'),
            `Are you sure you want to delete '${name}' from storage? This cannot be undone.`,
            async () => {
              try {
                await api.delete(`/api/vms/isos?path=${encodeURIComponent(path)}`);
                showToast(t('toast.iso_deleted_successfully', 'ISO \'{name}\' deleted successfully.', { name: name }), 'info');
                await loadVmDashboard();
                renderLocalIsoList();
                renderCatalogCards();
                document.getElementById('fm-refresh-btn')?.click();
              } catch (err) {
                showToast(t('toast.failed_to_delete_iso', 'Failed to delete ISO: {error}', { error: err.message }), 'error');
              }
            }
          );
        };
      });
    }
  }

  // Live Catalog Downloader & Task Poller
  function trackDownload(catalogId, taskId) {
    if (_isoPollTimers[catalogId]) clearInterval(_isoPollTimers[catalogId]);
    _isoPollTimers[catalogId] = setInterval(async () => {
      try {
        const tasks = await api.get('/api/vms/catalog/tasks');
        const task = (tasks || []).find((t) => t.catalog_id === catalogId || t.task_id === taskId);
        if (!task) return;

        const targetProg = modal.querySelector(`#prog-wrap-${catalogId}`);
        const targetBar = modal.querySelector(`#prog-bar-${catalogId}`);
        const targetPct = modal.querySelector(`#prog-pct-${catalogId}`);
        const targetStat = modal.querySelector(`#prog-stat-${catalogId}`);
        const btn = modal.querySelector(`.btn-dl-catalog[data-id="${catalogId}"]`);

        if (targetProg) targetProg.style.display = 'block';
        if (targetBar) targetBar.style.width = `${task.progress_pct || 0}%`;
        if (targetPct) targetPct.textContent = `${task.progress_pct || 0}%`;

        if (task.status === 'downloading') {
          if (targetStat) {
            targetStat.textContent = `Downloading... ${task.speed_mb_s || 0} MB/s (${task.progress_pct || 0}%)`;
            targetStat.style.color = '#38bdf8';
          }
          if (btn) {
            btn.disabled = true;
            btn.textContent = t('ui.downloading', '⏳ Downloading...');
          }
        } else if (task.status === 'completed') {
          clearInterval(_isoPollTimers[catalogId]);
          delete _isoPollTimers[catalogId];
          if (targetBar) targetBar.style.width = '100%';
          if (targetPct) targetPct.textContent = t('preview.actual_size', '100%');
          if (targetStat) {
            targetStat.textContent = t('ui.downloaded_to_mnt_user_isos', 'Downloaded to /mnt/user/isos');
            targetStat.style.color = '#34d399';
          }
          if (btn) {
            btn.disabled = false;
            btn.textContent = t('ui.ready', '✓ Ready');
            btn.style.background = 'rgba(16,185,129,0.2)';
            btn.style.borderColor = '#34d399';
            btn.style.color = '#34d399';
          }
          showToast(t('toast.downloaded_to_mnt_user_isos', 'Downloaded \'{name}\' to /mnt/user/isos', { name: task.name || catalogId }), 'success');
          await loadVmDashboard();
          renderCatalogCards();
          renderLocalIsoList();
          document.getElementById('fm-refresh-btn')?.click();
        } else if (task.status === 'failed' || task.status === 'checksum_mismatch') {
          clearInterval(_isoPollTimers[catalogId]);
          delete _isoPollTimers[catalogId];
          if (targetStat) {
            targetStat.textContent = `Failed: ${task.error || 'Verification error'}`;
            targetStat.style.color = '#ef4444';
          }
          if (btn) {
            btn.disabled = false;
            btn.textContent = t('ui.retry', '⬇ Retry');
            btn.style.opacity = '1';
          }
          showToast(t('toast.download_failed', 'Download failed: {error}', { error: task.error || 'Error' }), 'error');
        }
      } catch (_) {}
    }, 800);
  }

  // Render Official Catalog Cards with Real Live In-Storage Detection
  function renderCatalogCards(catalogList) {
    const container = modal.querySelector('#catalog-grid-container');
    if (!container) return;

    const list = catalogList || OFFICIAL_ISO_CATALOG;
    container.innerHTML = list.map((item) => {
      const inStorage = (vmState.isos || []).some((iso) =>
        iso.name.toLowerCase() === item.filename.toLowerCase() ||
        (iso.path && iso.path.toLowerCase().endsWith(item.filename.toLowerCase()))
      );

      return `
        <div class="catalog-card glassmorphic-card" style="padding: 14px; border-radius: 8px; border: 1px solid var(--zn-line-8); background: var(--lt-b-121a2699, rgba(18,26,38,0.6));">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
            <div>
              <span style="font-size: var(--zn-fs-xs); font-weight: 800; padding: 2px 6px; border-radius: 4px; background: rgba(14,165,233,0.15); color: var(--zn-text-accent);">${item.badge}</span>
              ${inStorage ? `<span style="font-size: var(--zn-fs-xs); font-weight: 800; padding: 2px 6px; border-radius: 4px; background: rgba(16,185,129,0.2); color: var(--zn-text-ok); margin-left: 6px;">✓ In Storage</span>` : ''}
              <div style="font-weight: 700; color: var(--zn-text-strong); font-size: 13px; margin-top: 4px;">${escapeHtml(item.name)}</div>
            </div>
            <span style="font-size: var(--zn-fs-xs); font-weight: 700; color: var(--zn-text-muted);">${item.size_formatted}</span>
          </div>
          <div style="font-size: var(--zn-fs-xs); color: var(--muted); margin: 6px 0 12px 0; line-height: 1.4;">${escapeHtml(item.desc || item.description || '')}</div>
          
          <!-- Download Progress Bar (Hidden by default or shown if in-flight) -->
          <div id="prog-wrap-${item.id}" style="${inStorage ? 'display: block;' : 'display: none;'} margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; font-size: var(--zn-fs-xs); margin-bottom: 4px;">
              <span id="prog-stat-${item.id}" style="color: ${inStorage ? '#34d399' : '#38bdf8'};">${inStorage ? 'Downloaded to /mnt/user/isos' : 'Ready'}</span>
              <span id="prog-pct-${item.id}" style="color: var(--zn-text-strong); font-weight: 700;">${inStorage ? '100%' : '0%'}</span>
            </div>
            <div style="height: 6px; border-radius: 3px; background: var(--zn-glaze-10); overflow: hidden;">
              <div id="prog-bar-${item.id}" style="width: ${inStorage ? '100%' : '0%'}; height: 100%; background: ${inStorage ? '#10b981' : '#0ea5e9'}; transition: width 0.2s;"></div>
            </div>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
            <span style="font-size: var(--zn-fs-xs); color: var(--muted); font-family: monospace;">${item.arch || item.architecture || 'x86_64'} • ${item.kernel || 'Linux'}</span>
            <div style="display: flex; gap: 6px;">
              ${inStorage ? `
                <button class="btn-pill-toggle btn-boot-catalog-iso" data-filename="${escapeHtml(item.filename)}" style="background: rgba(14,165,233,0.18); color: var(--zn-text-accent); border-color: rgba(14,165,233,0.35);">
                  ▶ Boot VM
                </button>
                <button class="btn-save-preset btn-dl-catalog" data-id="${item.id}" disabled style="padding: 5px 10px; font-size: var(--zn-fs-xs); font-weight: 700; background: rgba(16,185,129,0.2); color: var(--zn-text-ok); border-color: #34d399;">
                  ✓ Ready
                </button>
              ` : `
                <button class="btn-save-preset btn-dl-catalog" data-id="${item.id}" style="padding: 5px 12px; font-size: var(--zn-fs-xs); font-weight: 700; background: var(--accent-cyan, #0ea5e9); color: var(--zn-text-strong);">
                  <span>⬇ Download</span>
                </button>
              `}
            </div>
          </div>
        </div>
      `;
    }).join('');

    // Bind 1-click Download buttons
    container.querySelectorAll('.btn-dl-catalog:not(:disabled)').forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.dataset.id;
        btn.disabled = true;
        btn.textContent = t('ui.connecting_2', '⏳ Connecting...');

        const targetProg = modal.querySelector(`#prog-wrap-${id}`);
        const targetStat = modal.querySelector(`#prog-stat-${id}`);
        if (targetProg) targetProg.style.display = 'block';
        if (targetStat) {
          targetStat.textContent = t('ui.contacting_download_mirror', 'Contacting download mirror...');
          targetStat.style.color = '#38bdf8';
        }

        try {
          const res = await api.post(`/api/vms/catalog/${id}/download`);
          if (res && res.status === 'already_present') {
            showToast(t('toast.iso_already_exists_in_mnt_user', `ISO already exists in /mnt/user/isos`), 'info');
            await loadVmDashboard();
            renderCatalogCards();
            renderLocalIsoList();
            return;
          }
          trackDownload(id, res.task_id);
        } catch (err) {
          showToast(t('toast.failed_to_initiate_download', 'Failed to initiate download: {error}', { error: err.message }), 'error');
          if (targetStat) {
            targetStat.textContent = `Error: ${err.message}`;
            targetStat.style.color = '#ef4444';
          }
          btn.disabled = false;
          btn.textContent = t('ui.retry', '⬇ Retry');
        }
      };
    });

    // Bind Boot buttons
    container.querySelectorAll('.btn-boot-catalog-iso').forEach((btn) => {
      btn.onclick = () => {
        const fn = btn.dataset.filename;
        const isoObj = (vmState.isos || []).find((i) => i.name.toLowerCase() === fn.toLowerCase());
        const isoPath = isoObj ? isoObj.path : `/mnt/user/isos/${fn}`;
        if (window.DockManager) window.DockManager.minimize('vm-iso-manager');
        else modal.style.display = 'none';
        openVmCreateModal();
        const select = document.getElementById('vm-create-iso');
        if (select) select.value = isoPath;
      };
    });
  }

  // Tab switching logic
  const tabBtnCatalog = modal.querySelector('#tab-btn-catalog');
  const tabBtnLocal = modal.querySelector('#tab-btn-local');
  const tabContentCatalog = modal.querySelector('#tab-content-catalog');
  const tabContentLocal = modal.querySelector('#tab-content-local');

  function switchTab(tab) {
    if (tab === 'local') {
      tabBtnLocal?.classList.add('active');
      tabBtnCatalog?.classList.remove('active');
      if (tabContentLocal) tabContentLocal.style.display = 'block';
      if (tabContentCatalog) tabContentCatalog.style.display = 'none';
    } else {
      tabBtnCatalog?.classList.add('active');
      tabBtnLocal?.classList.remove('active');
      if (tabContentCatalog) tabContentCatalog.style.display = 'block';
      if (tabContentLocal) tabContentLocal.style.display = 'none';
    }
  }

  if (tabBtnCatalog) tabBtnCatalog.onclick = () => switchTab('catalog');
  if (tabBtnLocal) tabBtnLocal.onclick = () => switchTab('local');
  switchTab(initialTab);

  if (window.DockManager) {
    window.DockManager.restore('vm-iso-manager');
  } else {
    modal.style.display = 'flex';
  }
  bringToFront(modal);

  if (modal._unbindTrap) {
    try { modal._unbindTrap(); } catch (_) {}
    modal._unbindTrap = null;
  }
  modal._unbindTrap = trapFocus(modal, () => {
    const closeBtn = modal.querySelector('#iso-modal-close');
    if (closeBtn) closeBtn.click();
    else {
      modal.classList.add('window-minimized');
      modal.classList.remove('open');
      modal.style.setProperty('display', 'none', 'important');
    }
  });

  // Load and render both tabs
  renderLocalIsoList();
  renderCatalogCards();

  // Fetch live catalog and active tasks from backend
  try {
    const [remoteCatalog, tasks] = await Promise.all([
      api.get('/api/vms/catalog').catch(() => null),
      api.get('/api/vms/catalog/tasks').catch(() => null),
    ]);

    if (remoteCatalog && remoteCatalog.length > 0) {
      renderCatalogCards(remoteCatalog);
    }

    if (tasks && tasks.length > 0) {
      tasks.forEach((t) => {
        if (t.status === 'downloading') {
          trackDownload(t.catalog_id, t.task_id);
        }
      });
    }
  } catch (_) {}
}
