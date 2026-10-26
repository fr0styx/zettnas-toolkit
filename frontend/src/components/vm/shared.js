// Small helpers the VM window and its dialogs share.
// Part of vm-manager.js, split out by ARC-5.

import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { vmState } from './state.js';

export // vTPM needs the swtpm emulator on the host; warn instead of promising Windows 11 support.
function vtpmBadgeHtml() {
  if (vmState.telemetry?.kvm?.vtpm_available === false) {
    return `<span class="vm-tpm-badge unavailable" title="${escapeHtml(t('vm.tpm_unavailable_hint', 'Install the swtpm package on the host (or update the container image) to use vTPM.'))}" style="font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px; background: rgba(245,158,11,0.15); color: var(--zn-text-warn); border: 1px solid rgba(245,158,11,0.3);">⚠️ ${escapeHtml(t('vm.tpm_unavailable', 'swtpm not installed'))}</span>`;
  }
  return `<span class="vm-tpm-badge" style="font-size: var(--zn-fs-xs); padding: 2px 6px; border-radius: 4px; background: rgba(14,165,233,0.15); color: var(--zn-text-accent); border: 1px solid rgba(14,165,233,0.3);">🛡️ ${escapeHtml(t('vm.tpm_ready', 'Windows 11 Ready'))}</span>`;
}
