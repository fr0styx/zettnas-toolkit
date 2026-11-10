// VM snapshots: list, take, restore, delete.
// Part of vm-manager.js, split out by ARC-5.

import { api } from '../../api.js';
import { escapeHtml, trapFocus } from '../../utils.js';
import { showToast, showConfirmToast } from '../../toast.js';
import { t } from '../../i18n.js';
import { makeDraggable } from '../dock.js';
import { vmState } from './state.js';
import { openVmConnectModal } from './connect-modal.js';
import { openVmEditModal } from './edit-modal.js';
import { loadVmDashboard } from '../vm-manager.js';

export async function openVmSnapshotsModal(vmId, vmObj = null) {
  let modal = document.getElementById('modal-vm-snapshots');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'modal-vm-snapshots';
    modal.className = 'smart-modal-backdrop';
    document.body.appendChild(modal);
  } else {
    modal.className = 'smart-modal-backdrop';
  }

  const targetVm = vmObj || vmState.list.find((v) => v.id === vmId) || { id: vmId, name: 'Virtual Machine', state: 'stopped' };
  let activeTab = 'snapshots';

  modal.innerHTML = `
    <div class="smart-modal-window vm-modal-window vmsn-col">
      <div class="smart-modal-header vmsn-row">
        <div class="smart-modal-title vmsn-row-2">
          <svg class="vmsn-accent" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
          <span>${t('vm.snapshots', 'Snapshots & Rollback')}: ${escapeHtml(targetVm.name)}</span>
        </div>
        <div class="os-window-controls vmsn-row-3">
          <button class="win-btn close-btn" id="vm-snap-modal-close" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
        </div>
      </div>

      <!-- Navigation Tabs -->
      <div style="display: flex; gap: 8px; border-bottom: 1px solid var(--zn-line-8); padding: 8px 18px; background: var(--lt-b-00000026, rgba(0,0,0,0.15));">
        <button type="button" id="tab-btn-snaps" class="btn-pill-toggle active">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
          <span>${t('vsn.tab_snaps', 'Snapshots (QCOW2)')}</span>
        </button>
        <button type="button" id="tab-btn-backups" class="btn-pill-toggle">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          <span>${t('vsn.tab_backups', 'Backups (.tar.gz)')}</span>
        </button>
      </div>

      <div class="smart-modal-body vmsn-col-2">
        <!-- SNAPSHOTS PANE -->
        <div class="vmsn-x" id="vm-pane-snapshots" style="display: flex;">
          <div class="vmsn-row-4">
            <div>
              <div class="vmsn-xs-bold-strong">${t('vsn.snaps_title', 'Snapshots of this VM')}</div>
              <div class="vmsn-xs-muted">${t('vsn.snaps_desc', 'While the VM runs, a snapshot saves its memory and disk; while it is off, the disk only.')}</div>
            </div>
            <button type="button" id="btn-take-snapshot" class="btn-pill-toggle" style="background: rgba(51,205,184,0.15); border: 1px solid rgba(51,205,184,0.35); color: var(--zn-text-accent);">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span>${t('vm.take_snapshot', '+ Take Snapshot')}</span>
            </button>
          </div>

          <!-- Create Snapshot Form -->
          <div id="vm-snap-create-form" style="display: none; background: var(--zn-shade-30); border: 1px solid rgba(51,205,184,0.3); border-radius: 8px; padding: 12px; flex-direction: column; gap: 10px;">
            <div class="vmsn-xs-bold-accent">${t('vsn.new_title', 'New snapshot')}</div>
            <div class="vmsn-row-5">
              <input class="vmsn-xs-strong-box-grow" type="text" id="vm-snap-name-input" placeholder="${t('vm.snapshot_name', 'Snapshot Name')}" />
              <input class="vmsn-xs-strong-box-grow-2" type="text" id="vm-snap-desc-input" placeholder="${t('vm.snapshot_desc', 'Description (optional)')}" />
            </div>
            <div class="vmsn-row-6">
              <button type="button" id="btn-cancel-take-snapshot" class="btn-pill-toggle">${t('common.cancel', 'Cancel')}</button>
              <button type="button" id="btn-submit-take-snapshot" class="btn-pill-toggle is-primary">${t('ui.save_snapshot', 'Save Snapshot')}</button>
            </div>
          </div>

          <div class="vmsn-box" id="vm-snapshots-container">
            <div class="vmsn-xs-muted-center">${t('vsn.loading', 'Loading snapshots…')}</div>
          </div>
        </div>

        <!-- BACKUPS PANE -->
        <div class="vmsn-x" id="vm-pane-backups" style="display: none;">
          <div class="vmsn-row-4">
            <div>
              <div class="vmsn-xs-bold-strong">${t('vsn.bk_title', 'Full VM backups')}</div>
              <div class="vmsn-xs-muted">${t('vsn.bk_desc', 'Archives (.tar.gz) that hold the VM’s settings and its disks.')}</div>
            </div>
            <button type="button" id="btn-create-hyper-backup" class="btn-pill-toggle" style="background: rgba(16,185,129,0.15); border: 1px solid rgba(16,185,129,0.35); color: var(--zn-text-ok);">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span>${t('ui.create_hyper_backup', '+ Back up now')}</span>
            </button>
          </div>

          <div class="vmsn-box" id="vm-backups-container">
            <div class="vmsn-xs-muted-center">${t('vsn.bk_loading', 'Loading backups…')}</div>
          </div>
        </div>
      </div>
    </div>
  `;

  modal.classList.remove('window-minimized');
  modal.classList.add('open');
  modal.style.removeProperty('display');
  modal.style.setProperty('display', 'flex', 'important');
  modal.style.zIndex = '9600';

  const win = modal.querySelector('.smart-modal-window');
  if (win) {
    win.style.zIndex = '9610';
    makeDraggable(win, modal.querySelector('.smart-modal-header'));
  }

  // Close wiring
  const close = () => {
    modal.classList.remove('open');
    modal.classList.add('window-minimized');
    modal.style.setProperty('display', 'none', 'important');
    if (modal._unbindTrap) {
      try { modal._unbindTrap(); } catch (_) {}
      modal._unbindTrap = null;
    }
  };

  const closeBtn = modal.querySelector('#vm-snap-modal-close');
  if (closeBtn) closeBtn.onclick = close;
  modal.onclick = (e) => {
    if (e.target === modal) close();
  };

  if (modal._unbindTrap) {
    try { modal._unbindTrap(); } catch (_) {}
    modal._unbindTrap = null;
  }
  modal._unbindTrap = trapFocus(modal, close);

  // Tab switching
  const tabSnaps = modal.querySelector('#tab-btn-snaps');
  const tabBackups = modal.querySelector('#tab-btn-backups');
  const paneSnaps = modal.querySelector('#vm-pane-snapshots');
  const paneBackups = modal.querySelector('#vm-pane-backups');

  if (tabSnaps && tabBackups) {
    tabSnaps.onclick = () => {
      activeTab = 'snapshots';
      tabSnaps.classList.add('active');
      tabBackups.classList.remove('active');
      paneSnaps.style.display = 'flex';
      paneBackups.style.display = 'none';
      loadSnapshotsList();
    };
    tabBackups.onclick = () => {
      activeTab = 'backups';
      tabBackups.classList.add('active');
      tabSnaps.classList.remove('active');
      paneBackups.style.display = 'flex';
      paneSnaps.style.display = 'none';
      loadBackupsList();
    };
  }

  // Snapshot form wiring
  const btnTake = modal.querySelector('#btn-take-snapshot');
  const createForm = modal.querySelector('#vm-snap-create-form');
  const nameInput = modal.querySelector('#vm-snap-name-input');
  const descInput = modal.querySelector('#vm-snap-desc-input');
  const btnCancel = modal.querySelector('#btn-cancel-take-snapshot');
  const btnSubmit = modal.querySelector('#btn-submit-take-snapshot');

  const defaultSnapName = () => `snap-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}-${new Date().toTimeString().slice(0, 8).replace(/:/g, '')}`;

  if (btnTake && createForm) {
    btnTake.onclick = () => {
      createForm.style.display = createForm.style.display === 'none' ? 'flex' : 'none';
      if (createForm.style.display === 'flex' && nameInput) {
        nameInput.value = defaultSnapName();
        nameInput.focus();
      }
    };
  }

  if (btnCancel && createForm) {
    btnCancel.onclick = () => { createForm.style.display = 'none'; };
  }

  async function loadSnapshotsList() {
    const container = modal.querySelector('#vm-snapshots-container');
    if (!container) return;
    try {
      const data = await api.get(`/api/vms/${vmId}/snapshots`);
      const snaps = data?.snapshots || [];
      if (snaps.length === 0) {
        container.innerHTML = `
          <div class="vmsn-col-xs-muted-center">
            <svg class="vmsn-x-2" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
            <span>${t('vm.no_snapshots', 'No snapshots yet. Take one before a big update, so you can go back.')}</span>
          </div>
        `;
        return;
      }

      container.innerHTML = `
        <table class="vmsn-xs-box">
          <thead>
            <tr class="vmsn-muted-box">
              <th class="vmsn-x-3">${t('vsn.h_name', 'Name')}</th>
              <th class="vmsn-x-3">${t('vsn.h_time', 'Taken')}</th>
              <th class="vmsn-x-3">${t('vsn.h_size', 'Size')}</th>
              <th class="vmsn-x-3">${t('vsn.h_mode', 'Type')}</th>
              <th class="vmsn-x-4">${t('vsn.h_actions', 'Actions')}</th>
            </tr>
          </thead>
          <tbody>
            ${snaps.map((s) => `
              <tr style="border-bottom: 1px solid var(--lt-r-ffffff0a, rgba(255,255,255,0.04));">
                <td class="vmsn-bold-strong">
                  <div>${escapeHtml(s.name)}</div>
                  ${s.description ? `<div class="vmsn-xs-muted-2">${escapeHtml(s.description)}</div>` : ''}
                </td>
                <td class="vmsn-muted-mono">${escapeHtml(s.date || s.created_at || '—')}</td>
                <td class="vmsn-muted">${escapeHtml(s.size_formatted || s.vm_size || '—')}</td>
                <td class="vmsn-x-3">
                  <span style="font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px; background: rgba(51,205,184,0.15); color: var(--zn-text-accent);">
                    ${s.is_live ? t('vsn.live', 'Memory and disk') : t('vsn.disk', 'Disk only')}
                  </span>
                </td>
                <td class="vmsn-x-4">
                  <div class="vmsn-row-7">
                    <button class="btn-pill-toggle btn-snap-revert" data-name="${escapeHtml(s.name)}" style="color: var(--zn-text-accent); border-color: rgba(51,205,184,0.3);">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="11 17 6 12 11 7"/><polyline points="18 17 13 12 18 7"/></svg>
                      <span>${t('vm.revert_snapshot', 'Revert')}</span>
                    </button>
                    <button class="btn-pill-toggle btn-snap-del is-danger" data-name="${escapeHtml(s.name)}">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                      <span>${t('vm.delete_snapshot', 'Delete')}</span>
                    </button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;

      container.querySelectorAll('.btn-snap-revert').forEach((b) => {
        b.onclick = () => {
          const snapName = b.dataset.name;
          showConfirmToast(
            t('vsn.revert_q', 'Go back to the snapshot “{snap}” of {name}? Changes made since then are lost.', { snap: snapName, name: targetVm.name }),
            async () => {
              try {
                await api.post(`/api/vms/${vmId}/snapshots/${encodeURIComponent(snapName)}/revert`);
                showToast(t('toast.rolled_back_vm_to_snapshot', 'Rolled back VM \'{name}\' to snapshot \'{snapName}\'.', { name: targetVm.name, snapName: snapName }), 'success');
                loadSnapshotsList();
                loadVmDashboard();
              } catch (err) {
                showToast(t('toast.revert_failed', 'Revert failed: {error}', { error: err.message || err.detail }), 'error');
              }
            }
          );
        };
      });

      container.querySelectorAll('.btn-snap-del').forEach((b) => {
        b.onclick = () => {
          const snapName = b.dataset.name;
          showConfirmToast(
            t('vsn.del_q', 'Delete the snapshot “{snap}”? This can’t be undone.', { snap: snapName }),
            async () => {
              try {
                await api.delete(`/api/vms/${vmId}/snapshots/${encodeURIComponent(snapName)}`, { confirmed: true });
                showToast(t('toast.deleted_snapshot', 'Deleted snapshot \'{snapName}\'.', { snapName: snapName }), 'success');
                loadSnapshotsList();
              } catch (err) {
                showToast(t('toast.delete_failed', 'Delete failed: {error}', { error: err.message || err.detail }), 'error');
              }
            }
          );
        };
      });
    } catch (err) {
      container.innerHTML = `<div class="vmsn-xs-crit-center">${escapeHtml(t('vsn.load_failed', 'Could not load the snapshots: {error}', { error: err.message || err.detail }))}</div>`;
    }
  }

  // VM backups loader
  async function loadBackupsList() {
    const container = modal.querySelector('#vm-backups-container');
    if (!container) return;
    try {
      const data = await api.get(`/api/vms/${vmId}/backups`);
      const backups = data?.backups || [];
      if (backups.length === 0) {
        container.innerHTML = `
          <div class="vmsn-col-xs-muted-center">
            <span class="vmsn-fs24">💾</span>
            <span>${t('vsn.no_backups', 'No backups of this VM yet. “Back up now” saves its settings and disks in one archive.')}</span>
          </div>
        `;
        return;
      }

      container.innerHTML = `
        <table class="vmsn-xs-box">
          <thead>
            <tr class="vmsn-muted-box">
              <th class="vmsn-x-3">${t('vsn.h_backup', 'Backup / file')}</th>
              <th class="vmsn-x-3">${t('vsn.h_created', 'Created')}</th>
              <th class="vmsn-x-3">${t('vsn.h_size', 'Size')}</th>
              <th class="vmsn-x-4">${t('vsn.h_actions', 'Actions')}</th>
            </tr>
          </thead>
          <tbody>
            ${backups.map((b) => `
              <tr style="border-bottom: 1px solid var(--lt-r-ffffff0a, rgba(255,255,255,0.04));">
                <td class="vmsn-bold-strong">
                  <div>${escapeHtml(b.filename || b.id)}</div>
                  <div class="vmsn-xs-muted-mono">${escapeHtml(b.id)}</div>
                </td>
                <td class="vmsn-muted-mono">${escapeHtml(b.created_at_iso || '—')}</td>
                <td class="vmsn-muted">${escapeHtml(b.size_formatted || '—')}</td>
                <td class="vmsn-x-4">
                  <div class="vmsn-row-7">
                    <button class="btn-pill-toggle btn-bk-restore" data-id="${escapeHtml(b.id)}" style="color: var(--zn-text-ok); border-color: rgba(16,185,129,0.3);">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
                      <span>${t('vsn.restore', 'Restore')}</span>
                    </button>
                    <button class="btn-pill-toggle btn-bk-del is-danger" data-id="${escapeHtml(b.id)}">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                      <span>${t('vm.delete', 'Delete')}</span>
                    </button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;

      container.querySelectorAll('.btn-bk-restore').forEach((b) => {
        b.onclick = () => {
          const bId = b.dataset.id;
          showConfirmToast(
            t('vsn.restore_q', 'Restore {name} from the backup “{id}”? Its disks and settings are replaced by the backup’s.', { name: targetVm.name, id: bId }),
            async () => {
              try {
                await api.post(`/api/vms/backups/${encodeURIComponent(bId)}/restore`);
                showToast(t('toast.restored_vm_from_backup', 'Restored VM \'{name}\' from backup \'{bId}\'.', { name: targetVm.name, bId: bId }), 'success');
                loadBackupsList();
                loadVmDashboard();
              } catch (err) {
                showToast(t('toast.restore_failed', 'Restore failed: {error}', { error: err.message || err.detail }), 'error');
              }
            }
          );
        };
      });

      container.querySelectorAll('.btn-bk-del').forEach((b) => {
        b.onclick = () => {
          const bId = b.dataset.id;
          showConfirmToast(
            t('vsn.del_bk_q', 'Delete the backup “{id}”? This can’t be undone.', { id: bId }),
            async () => {
              try {
                await api.delete(`/api/vms/backups/${encodeURIComponent(bId)}`, { confirmed: true });
                showToast(t('toast.deleted_backup', 'Deleted backup \'{bId}\'.', { bId: bId }), 'success');
                loadBackupsList();
              } catch (err) {
                showToast(t('toast.delete_failed', 'Delete failed: {error}', { error: err.message || err.detail }), 'error');
              }
            }
          );
        };
      });
    } catch (err) {
      container.innerHTML = `<div class="vmsn-xs-crit-center">${escapeHtml(t('vsn.bk_failed', 'Could not load the backups: {error}', { error: err.message || err.detail }))}</div>`;
    }
  }

  // Back up a VM now
  const btnCreateBackup = modal.querySelector('#btn-create-hyper-backup');
  if (btnCreateBackup) {
    btnCreateBackup.onclick = async () => {
      btnCreateBackup.disabled = true;
      btnCreateBackup.textContent = t('ui.archiving', 'Archiving...');
      try {
        await api.post(`/api/vms/${vmId}/backup`, { reason: 'on-demand' });
        showToast(t('toast.hyper_backup_created_for_vm', 'Backup of VM \'{name}\' saved.', { name: targetVm.name }), 'success');
        loadBackupsList();
      } catch (err) {
        showToast(t('toast.failed_creating_hyper_backup', 'Backup failed: {error}', { error: err.message || err.detail }), 'error');
      } finally {
        btnCreateBackup.disabled = false;
        btnCreateBackup.textContent = t('ui.create_hyper_backup', '+ Back up now');
      }
    };
  }

  // Submit snapshot
  if (btnSubmit) {
    btnSubmit.onclick = async () => {
      const name = (nameInput?.value || '').trim();
      const description = (descInput?.value || '').trim();
      if (!name) {
        showToast(t('toast.please_specify_a_snapshot_name', 'Please specify a snapshot name'), 'warning');
        return;
      }
      btnSubmit.disabled = true;
      btnSubmit.textContent = t('ui.saving', 'Saving...');
      try {
        await api.post(`/api/vms/${vmId}/snapshots`, { name, description });
        showToast(t('toast.snapshot_created_successfully', 'Snapshot \'{name}\' created successfully.', { name: name }), 'success');
        if (createForm) createForm.style.display = 'none';
        if (descInput) descInput.value = '';
        loadSnapshotsList();
      } catch (err) {
        showToast(t('toast.failed_to_create_snapshot', 'Failed to create snapshot: {error}', { error: err.message || err.detail }), 'error');
      } finally {
        btnSubmit.disabled = false;
        btnSubmit.textContent = t('ui.save_snapshot', 'Save Snapshot');
      }
    };
  }

  loadSnapshotsList();
}

if (typeof window !== 'undefined') {
  window.openVmConnectModal = openVmConnectModal;
  window.openVmEditModal = openVmEditModal;
  window.openVmSnapshotsModal = openVmSnapshotsModal;
}
