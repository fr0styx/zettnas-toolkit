// A virtual machine's power: the questions asked before an action, what a card shows while its
// machine shuts down, and the small rules the forms share (SET-07).
// "Shut down" asks the system inside and never ends it; only "Turn off now" does.

import { escapeHtml } from '../../utils.js';
import { showConfirmToast, showDangerConfirm } from '../../toast.js';
import { t } from '../../i18n.js';

/** True while a machine has been asked to shut down and still runs. */
export const isShuttingDown = (vm) => vm?.state === 'shutting_down';

/** True when no part of the machine runs: only then are snapshots made, restored or deleted. */
export const isOff = (vm) => !['running', 'paused', 'shutting_down'].includes(String(vm?.state || 'stopped'));

/** The read-only choice of a shared folder. The create form saved it as mode "ro", the edit form
 *  as readonly true, and each form read only its own. */
export const shareReadOnly = (share) => share?.mode === 'ro' || share?.readonly === true;

/** A shared folder as both forms now save it. */
export function shareRecord(hostPath, mountTag, driver, readOnly) {
  return { host_path: hostPath, mount_tag: mountTag, driver, mode: readOnly ? 'ro' : 'rw', readonly: !!readOnly };
}

/** The server's list of snapshots. It is a plain list; the dialog read `data.snapshots` and so
 *  always showed "No snapshots yet". */
export const snapshotList = (data) => (Array.isArray(data) ? data : data?.snapshots || []);

/** Whether the list should be read again by itself: while a machine shuts down. */
export const needsWatching = (vms) => (vms || []).some(isShuttingDown);

/**
 * Asks before a power action and calls `run` on yes. Shut down, Turn off now and Restart are
 * asked about; anything else runs at once.
 * @param {string} action
 * @param {string} name
 * @param {() => void} run
 */
export function askPower(action, name, run) {
  if (action === 'stop' || action === 'acpi_shutdown') {
    showConfirmToast(
      t('vmp.shutdown_title', 'Shut down {name}?', { name }),
      t('vmp.shutdown_msg', 'The system inside is asked to shut down, as if you pressed its power button. Kiboto waits for it and does not end it.'),
      run,
      null,
      { okText: t('vmm.shutdown', 'Shut down'), destructive: false }
    );
    return;
  }
  if (action === 'force_off') {
    showDangerConfirm(
      t('vmp.off_title', 'Turn off {name} now?', { name }),
      t('vmp.off_msg', 'This is like pulling the plug. Work that was not saved inside is lost, and its disk can be damaged.'),
      run,
      null,
      { okText: t('vmm.force_stop', 'Turn off now') }
    );
    return;
  }
  if (action === 'restart' || action === 'reboot') {
    showDangerConfirm(
      t('vmp.restart_title', 'Restart {name}?', { name }),
      t('vmp.restart_msg', 'This presses its reset button. The system inside is not shut down first, so work that was not saved is lost.'),
      run,
      null,
      { okText: t('vmm.restart', 'Restart') }
    );
    return;
  }
  run();
}

/**
 * What to say once the server has answered an action.
 * @param {string} action
 * @param {string | undefined} state the state the server answered with
 * @param {string} name
 * @returns {{ text: string, tone: string }}
 */
export function powerToast(action, state, name) {
  if (state === 'shutting_down') return { text: t('vmp.asked', '{name} was asked to shut down.', { name }), tone: 'info' };
  if (action === 'stop' || action === 'acpi_shutdown') return { text: t('vmp.is_off', '{name} is off.', { name }), tone: 'success' };
  if (action === 'force_off') return { text: t('vmp.turned_off', '{name} was turned off.', { name }), tone: 'success' };
  if (action === 'start') return { text: t('vmp.started', '{name} started.', { name }), tone: 'success' };
  if (action === 'restart' || action === 'reboot') return { text: t('vmp.restarted', '{name} was restarted.', { name }), tone: 'success' };
  if (action === 'pause') return { text: t('vmp.paused', '{name} is paused.', { name }), tone: 'success' };
  if (action === 'resume') return { text: t('vmp.resumed', '{name} runs again.', { name }), tone: 'success' };
  return { text: t('toast.vm_action_completed', "VM action '{action}' completed", { action }), tone: 'success' };
}

/** The buttons of a card while its machine shuts down: nothing to press at first, and
 *  "Turn off now" once the server offers it (after two minutes). */
export function shuttingDownActionsHtml(vm) {
  const id = escapeHtml(vm.id);
  if (!vm.turn_off_offered) {
    return `<span class="vm-shutting-note vmm-xs-muted" role="status">${escapeHtml(t('vmp.shutting', 'Shutting down. The system inside is finishing.'))}</span>`;
  }
  return `
    <span class="vm-shutting-note is-late vmm-xs-muted" role="status">${escapeHtml(t('vmp.shutting_late', 'Has not shut down after two minutes.'))}</span>
    <button class="btn-vm-action btn-vm-stop btn-vm-force-off vmm-grow-2" data-id="${id}" data-act="force_off">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
      <span>${escapeHtml(t('vmm.force_stop', 'Turn off now'))}</span>
    </button>`;
}
