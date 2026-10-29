/**
 * Immich in AI settings and search results (Batch 6).
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';

export function immichResultsHtml(items) {
  if (!items || !items.length) return '';
  return `<section class="immich-strip" aria-label="${escapeHtml(t('immich.from', 'From your Immich'))}">
    <h4>${escapeHtml(t('immich.from', 'From your Immich'))}</h4>
    <ul>${items
      .map(
        (p) => `<li><a href="${escapeHtml(p.immich_url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(p.name)}">
          <img src="${escapeHtml(p.thumbnail_url)}" alt="${escapeHtml(p.name)}" loading="lazy" width="120" height="90"></a></li>`,
      )
      .join('')}</ul></section>`;
}

/** Opens Settings → Backups at the "Back up my phone" card. */
export function openPhoneBackup() {
  if (typeof window.openManagementWindow !== 'function') return;
  window.openManagementWindow('mgmt-pane-backups');
  setTimeout(() => document.getElementById('phone-backup-mount')?.scrollIntoView?.({ block: 'start' }), 300);
}

export function settingsHtml(s, isAdmin) {
  return `<p class="immich-note">${escapeHtml(t('immich.desc', 'When Immich runs next to ZettNAS, photo searches also show your Immich photos. Each person connects their own Immich account.'))}</p>
    <p class="immich-note">${escapeHtml(t('immich.phone_backup_hint', "To back up a phone's photos here, follow the steps under Backups."))}
      <button type="button" class="btn-pill-toggle is-small" data-immich-phone-backup>${escapeHtml(t('immich.phone_backup_open', 'Back up my phone'))}</button></p>
    ${
      isAdmin
        ? `<form class="immich-form" data-immich-url><label>${escapeHtml(t('immich.address', 'Immich address'))}<input name="url" value="${escapeHtml(s.url || s.detected || '')}" placeholder="http://192.168.1.10:2283"></label>
      <button type="submit" class="btn-pill-toggle">${escapeHtml(t('immich.save_address', 'Save address'))}</button></form>`
        : ''
    }
    ${
      s.connected
        ? `<p>${escapeHtml(t('immich.connected', 'Your Immich is connected.'))} <button type="button" class="btn-pill-toggle is-small" data-immich-disconnect>${escapeHtml(t('immich.disconnect', 'Disconnect'))}</button></p>`
        : `<form class="immich-form" data-immich-key><label>${escapeHtml(t('immich.key', 'Your Immich API key (Immich → Account settings → API keys)'))}<input name="api_key" type="password" autocomplete="off" minlength="20"></label>
      <button type="submit" class="btn-pill-toggle is-primary"${s.url ? '' : ` disabled title="${escapeHtml(t('immich.need_address', 'An administrator sets the Immich address first'))}"`}>${escapeHtml(t('immich.connect', 'Connect my Immich'))}</button></form>`
    }`;
}

export async function renderImmichSettings(mount, isAdmin = false) {
  if (!mount) return;
  let s;
  try {
    s = await api.get('/api/immich');
  } catch (e) {
    mount.hidden = true;
    return;
  }
  mount.innerHTML = settingsHtml(s, isAdmin);
  // one place to back up a phone, under Backups (UX-25)
  mount.querySelector('[data-immich-phone-backup]')?.addEventListener('click', () => openPhoneBackup());
  mount.querySelector('[data-immich-url]')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await api.put('/api/immich/url', { url: new FormData(e.target).get('url') });
      renderImmichSettings(mount, isAdmin);
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  });
  mount.querySelector('[data-immich-key]')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const r = await api.put('/api/immich/me', { api_key: new FormData(e.target).get('api_key') });
      showToast(t('immich.hello', 'Connected to Immich as {name}.', { name: r.immich_user || '' }), 'success');
      renderImmichSettings(mount, isAdmin);
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  });
  mount.querySelector('[data-immich-disconnect]')?.addEventListener('click', async () => {
    await api.delete('/api/immich/me');
    renderImmichSettings(mount, isAdmin);
  });
}
