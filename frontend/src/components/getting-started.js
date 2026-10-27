/**
 * Getting started (UX-1): what a new owner still has to do, from /api/setup/checklist, with a
 * button that opens the right place. Shown on the desktop until everything is done or it is
 * hidden; window.openGettingStarted() brings it back.
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';

const HIDDEN_KEY = 'zettnas_getting_started_hidden';
const ITEMS = {
  password: ['gs.password', 'Choose your own password', 'gs.password_desc', 'Replace the first-time password.'],
  two_factor: ['gs.two_factor', 'Turn on two-factor sign-in', 'gs.two_factor_desc', 'A code from your phone, on top of the password.'],
  share: ['gs.share', 'Create a share', 'gs.share_desc', 'A folder your computers and phones can open over the network.'],
  share_host: ['gs.share_host', 'Make a shared folder in {host}', 'gs.share_host_desc', '{host} creates shared folders; ZettNAS lists them under Shares.'],
  app: ['gs.app', 'Install an app', 'gs.app_desc', 'Photos, media, home automation and more from the app catalog.'],
  backup: ['gs.backup', 'Set up a backup', 'gs.backup_desc', 'Copy your files, and ZettNAS settings, somewhere else on a schedule.'],
  alerts: ['gs.alerts', 'Get alerts', 'gs.alerts_desc', 'Hear about failing disks and power cuts on your phone or by email.'],
  ai_folder: ['gs.ai_folder', 'Let AI learn a folder', 'gs.ai_folder_desc', 'Search and ask questions about your own documents, privately.'],
  phone_backup: ['gs.phone_backup', 'Back up your phone', 'gs.phone_backup_desc', 'Photos from your phone copied here automatically, with Immich.'],
};

function isHidden() {
  try {
    return localStorage.getItem(HIDDEN_KEY) === '1';
  } catch (e) {
    return false;
  }
}

function setHidden(v) {
  try {
    if (v) localStorage.setItem(HIDDEN_KEY, '1');
    else localStorage.removeItem(HIDDEN_KEY);
  } catch (e) {
    /* storage blocked */
  }
}

const hostName = (h) => {
  const s = String(h || '');
  return s === 'truenas' ? 'TrueNAS' : s.charAt(0).toUpperCase() + s.slice(1);
};

export function checklistHtml(data) {
  const rows = (data.items || []).map((item) => {
    const [tk, tf, dk, df] = ITEMS[item.id] || [item.id, item.id, '', ''];
    const action = item.done
      ? `<span class="gs-done" role="img" aria-label="${escapeHtml(t('gs.done', 'Done'))}">✓</span>`
      : `<button type="button" class="btn-pill-toggle is-primary is-small gs-open" data-gs-open="${escapeHtml(item.open)}">${escapeHtml(t('gs.open', 'Open'))}</button>`;
    return `<li class="gs-item${item.done ? ' is-done' : ''}">
      <div class="gs-text"><span class="gs-title">${escapeHtml(t(tk, tf, { host: hostName(item.host) }))}</span><span class="gs-desc">${escapeHtml(t(dk, df, { host: hostName(item.host) }))}</span></div>
      ${action}</li>`;
  });
  return `<div class="gs-head">
      <h2 class="gs-heading" id="gs-heading">${escapeHtml(t('gs.title', 'Getting started'))}</h2>
      <span class="gs-progress">${escapeHtml(t('gs.progress', '{done} of {total} done', { done: data.done, total: data.total }))}</span>
      <button type="button" class="btn-pill-toggle is-ghost is-small gs-hide" data-gs-hide>${escapeHtml(t('gs.hide', 'Hide'))}</button>
    </div>
    <ul class="gs-list">${rows.join('')}</ul>`;
}

export async function showGettingStarted({ force = false } = {}) {
  if (!force && isHidden()) return null;
  let data;
  try {
    data = await api.get('/api/setup/checklist');
  } catch (e) {
    return null;
  }
  if (!data || (data.complete && !force)) return data;
  let card = document.getElementById('getting-started-card');
  if (!card) {
    card = document.createElement('section');
    card.id = 'getting-started-card';
    card.className = 'getting-started-card';
    card.setAttribute('aria-labelledby', 'gs-heading');
    document.body.appendChild(card);
    card.addEventListener('click', (e) => {
      const open = e.target.closest('[data-gs-open]');
      if (open && typeof window.openManagementSection === 'function') {
        window.openManagementSection(open.dataset.gsOpen);
      } else if (open && typeof window.openManagementWindow === 'function') {
        window.openManagementWindow(open.dataset.gsOpen);
      }
      if (e.target.closest('[data-gs-hide]')) {
        setHidden(true);
        card.hidden = true;
      }
    });
  }
  card.innerHTML = checklistHtml(data);
  card.hidden = false;
  return data;
}

export function initGettingStarted() {
  window.openGettingStarted = () => {
    setHidden(false);
    return showGettingStarted({ force: true });
  };
  setTimeout(() => showGettingStarted(), 1500);
}
