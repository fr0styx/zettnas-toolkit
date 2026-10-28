/**
 * "Protect this NAS" (FEAT-01): a copy of the shares outside this box in one step. Pick where it
 * goes (a USB disk, another NAS or the cloud), keep or narrow the shares, and it becomes an
 * off-site backup (restic: versions, encrypted) that runs every night at 2:00; the first run
 * starts right away and the recovery kit is offered.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { html } from '../html.js';
import { showToast } from '../toast.js';
import { offerRecoveryKit } from './offsite-backup.js';

const KINDS = [
  {
    kind: 'usb',
    label: () => t('protect.usb', 'A USB disk'),
    help: () => t('protect.usb_help', 'Plugged into this NAS. Keep it somewhere else between backups if you can.'),
    none: () => t('protect.none_usb', 'No USB disk is mounted. Plug one in and mount it, then open this again.'),
  },
  {
    kind: 'nas',
    label: () => t('protect.nas', 'Another NAS'),
    help: () => t('protect.nas_help', 'A share of another NAS mounted here, best in another building.'),
    none: () => t('protect.none_nas', 'No other NAS is mounted here. Mount one of its shares, then open this again.'),
  },
  {
    kind: 'cloud',
    label: () => t('protect.cloud', 'The cloud'),
    help: () => t('protect.cloud_help', 'A cloud storage account set up in Remote storage.'),
    none: () => t('protect.none_cloud', 'No cloud storage is set up. Add it in Remote storage, then open this again.'),
  },
];

/** Shares left unticked at first: Docker's image and VM disks (system), installers (isos). They
 * are large, change all the time or can be downloaded again; anyone can still tick them. */
export const UNTICKED_SHARES = new Set(['system', 'isos']);

/** Where the backup goes inside the chosen destination. */
export function locationFor(kind, target) {
  return kind === 'cloud' ? `rclone:${target}:zettnas-backup` : `${String(target).replace(/\/+$/, '')}/zettnas-backup`;
}

export function guideHtml(dest, shares) {
  const where = KINDS.map((k) => {
    const options = (dest && dest[k.kind]) || [];
    return html`<fieldset class="protect-kind"><legend>${k.label()}</legend><p class="snap-help">${k.help()}</p>${
      options.length
        ? options.map((o) => html`<label class="offsite-check"><input type="radio" name="target" value="${k.kind}|${o}"> ${o}</label>`)
        : html`<p class="offsite-meta">${k.none()}</p>`
    }</fieldset>`;
  });
  const what = shares.map(
    (s) =>
      html`<label class="offsite-check"><input type="checkbox" name="paths" value="${s.path}" ${UNTICKED_SHARES.has(String(s.name).toLowerCase()) ? '' : html`checked`}> ${s.name}</label>`,
  );
  return html`<form class="offsite-form" data-protect-form>
    <p class="snap-help">${t('protect.intro', 'A copy of your shares outside this NAS, with versions and encryption, every night at 2:00.')}</p>
    ${where}
    <fieldset><legend>${t('protect.what', 'What')}</legend>${what}</fieldset>
    <button type="submit" class="btn-pill-toggle is-primary">${t('protect.create', 'Protect')}</button>
  </form>`;
}

/** Turns the form into an off-site backup; returns its id. */
export async function protect(form) {
  const f = new FormData(form);
  const target = String(f.get('target') || '');
  const paths = f.getAll('paths').map(String);
  if (!target) throw new Error(t('protect.pick', 'Pick where the copy goes.'));
  if (!paths.length) throw new Error(t('protect.pick_shares', 'Pick at least one share.'));
  const [kind, place] = [target.slice(0, target.indexOf('|')), target.slice(target.indexOf('|') + 1)];
  const id = `protect-${kind}-${Date.now().toString(36)}`;
  const name = `${(KINDS.find((k) => k.kind === kind) || KINDS[0]).label()}: ${place}`;
  await api.put('/api/offsite/repos', { id, name, location: locationFor(kind, place), paths, keep: {}, hour: 2 });
  await api.post(`/api/offsite/repos/${encodeURIComponent(id)}/init`, {});
  await api.post(`/api/offsite/repos/${encodeURIComponent(id)}/backup`, {});
  return id;
}

/** The window: centered on a dimmed backdrop, with the title bar every pop-up gets from
 * dialog-chrome.js (drag, minimize to the dock, maximize, close). */
function guideWindow() {
  let host = document.getElementById('protect-nas');
  if (!host) {
    host = document.createElement('div');
    host.id = 'protect-nas';
    host.className = 'smart-modal-backdrop';
    host.style.zIndex = '10020'; // above Mission Control
    host.innerHTML = html`<div class="smart-modal-window" role="dialog" aria-modal="true" aria-labelledby="protect-nas-title" data-dock-icon="#i-shield">
      <div class="smart-modal-header">
        <span class="smart-modal-title" id="protect-nas-title"><svg class="ic" aria-hidden="true"><use href="#i-shield"/></svg> ${t('protect.title', 'Protect this NAS')}</span>
        <div class="os-window-controls">
          <button type="button" class="win-btn close-btn" data-close title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
        </div>
      </div>
      <div class="smart-modal-body"></div>
    </div>`;
    document.body.appendChild(host);
    host.querySelector('[data-close]').addEventListener('click', () => closeGuide(host));
    host.addEventListener('click', (e) => {
      if (e.target === host) closeGuide(host);
    });
    host.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeGuide(host);
    });
  }
  return host;
}

export function closeGuide(host = document.getElementById('protect-nas')) {
  if (!host) return;
  host.classList.remove('open');
  host.style.display = 'none';
}

export async function openProtectGuide() {
  const host = guideWindow();
  const body = host.querySelector('.smart-modal-body');
  body.textContent = t('ui.loading', 'Loading...');
  host.style.display = '';
  host.classList.add('open');
  host.querySelector('[data-close]').focus();
  try {
    const [dest, sh] = await Promise.all([
      api.get('/api/offsite/destinations'),
      api.get('/api/storage/shares').catch(() => ({ shares: [] })),
    ]);
    const shares = (sh.shares || []).filter((s) => s.mountpoint).map((s) => ({ name: s.name, path: s.mountpoint }));
    body.innerHTML = guideHtml(dest, shares);
  } catch (err) {
    body.textContent = err.message || String(err);
    return host;
  }
  body.querySelector('[data-protect-form]').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const id = await protect(e.target);
      closeGuide(host);
      showToast(t('protect.done', 'Protection is set up and the first backup has started; it shows in Jobs. Save the recovery kit now.'), 'success');
      await offerRecoveryKit({ id });
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  });
  return host;
}
