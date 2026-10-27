/**
 * Protection jobs (B12a, REL-12): backups, snapshots and monthly scrubs in one list, each with
 * whether it is fine, failed, overdue, run by the host, or off; and the monthly scrub switch.
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { html } from '../../html.js';
import { formatDateTime } from '../../format.js';
import { showToast } from '../../toast.js';

const CARD_ID = 'protection-jobs-card';

const KIND = {
  backup: () => t('prot.kind_backup', 'Backup'),
  offsite: () => t('prot.kind_offsite', 'Off-site backup'),
  snapshot: () => t('prot.kind_snapshot', 'Snapshots'),
  scrub: () => t('prot.kind_scrub', 'Monthly check'),
};
const STATUS = {
  ok: () => t('prot.ok', 'Fine'),
  failed: () => t('prot.failed', 'Failed'),
  overdue: () => t('prot.overdue', 'Overdue'),
  host_owned: () => t('prot.host_owned', 'Run by the host'),
  unavailable: () => t('prot.unavailable', 'Not available'),
  off: () => t('prot.off', 'Off'),
};

const label = (map, key) => (map[key] || (() => key))();

function toggleHtml(j) {
  if (j.kind !== 'scrub' || !(j.status === 'off' || j.enabled)) return '';
  const name = t('prot.scrub_switch', 'Check {pool} for errors once a month', { pool: j.name });
  return html`<input type="checkbox" role="switch" data-scrub-pool="${j.id}" aria-label="${name}" ${j.enabled ? 'checked' : ''}>`;
}

export function jobsHtml(jobs) {
  if (!jobs.length) return html`<p class="zn-muted">${t('prot.none', 'Nothing protects your data yet. Set up a backup below.')}</p>`;
  return html`<table class="zn-table prot-table"><thead><tr><th>${t('prot.what', 'What')}</th><th>${t('prot.name', 'Name')}</th>
    <th>${t('prot.state', 'State')}</th><th>${t('prot.last_ok', 'Last success')}</th><th></th></tr></thead>
    <tbody>${jobs.map(
      (j) => html`<tr class="prot-row prot-${j.status}"><td>${label(KIND, j.kind)}</td><td>${j.name}</td>
        <td><span class="prot-status">${label(STATUS, j.status)}</span>${j.why ? html` <small class="zn-muted">${j.why}</small>` : ''}</td>
        <td>${j.last_ok ? formatDateTime(Number(j.last_ok) * 1000) : '—'}</td><td>${toggleHtml(j)}</td></tr>`,
    )}</tbody></table>`;
}

export async function renderProtectionJobs(card) {
  let data;
  try {
    data = await api.get('/api/protection/jobs');
  } catch {
    card.remove(); // no right to see it
    return;
  }
  card.innerHTML = html`<h4 class="my-alerts-title">${t('prot.title', 'What protects your data')}</h4>${jobsHtml(data.jobs || [])}`;
  card.querySelectorAll('[data-scrub-pool]').forEach((sw) => {
    sw.addEventListener('change', async () => {
      sw.disabled = true;
      try {
        // switching on for spinning disks asks to confirm first (428, handled by api.js)
        await api.put(`/api/protection/scrub/${encodeURIComponent(sw.dataset.scrubPool)}`, { enabled: sw.checked });
        await renderProtectionJobs(card);
      } catch (err) {
        sw.checked = !sw.checked;
        sw.disabled = false;
        if (err?.error !== 'cancelled') showToast(t('prot.save_failed', 'Could not change it: {error}', { error: err?.message || '' }), 'error');
      }
    });
  });
}

export async function installProtectionJobs(mount) {
  if (!mount) return;
  let card = document.getElementById(CARD_ID);
  if (!card) {
    card = document.createElement('section');
    card.id = CARD_ID;
    card.className = 'digest-card';
    mount.appendChild(card);
  }
  await renderProtectionJobs(card);
}
