// The installer images, read only when a dialog lists them. The window read the installer folders
// with every refresh and finished action, the pool's \`isos\` folder too, which can wake sleeping
// drives to draw a list (SET-14, VMs 28).

import { api } from '../../api.js';
import { escapeHtml } from '../../utils.js';
import { vmState } from './state.js';

/** Reads the installer list into vmState.isos; on a failure the last list stays. */
export async function loadIsos() {
  try {
    const isos = await api.get('/api/vms/isos');
    vmState.isos = Array.isArray(isos) ? isos : [];
  } catch (_) {
    // the dialog keeps the list it has
  }
  return vmState.isos;
}

/** Refills a select's installer options after its first ("none") option, keeping the choice. */
export function fillIsoSelect(select, selected = '') {
  if (!select) return;
  const keep = select.value || selected;
  const first = select.options[0] ? select.options[0].outerHTML : '';
  select.innerHTML = first + vmState.isos
    .map((iso) => `<option value="${escapeHtml(iso.path)}">${escapeHtml(iso.name)} (${escapeHtml(iso.size_formatted || '')})</option>`)
    .join('');
  if (keep) select.value = keep;
}
