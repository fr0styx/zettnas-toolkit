/**
 * AI for apps in AI settings (COMP-07): a key per app for the OpenAI-compatible endpoint, and
 * that app's settings filled in. Administrators only.
 */
import { api } from '../api.js';
import { escapeHtml, copyText } from '../utils.js';
import { t } from '../i18n.js';
import { showToast, showConfirmToast } from '../toast.js';
import { formatDateTime } from '../format.js';

function settingsText(settings) {
  return Object.entries(settings || {})
    .map(([k, v]) => `${k}=${v}`)
    .join('\n');
}

export function appsHtml(data) {
  const keys = data.keys || [];
  const options = (data.apps || [])
    .map((a) => `<option value="${escapeHtml(a.app)}">${escapeHtml(a.label)}</option>`)
    .join('');
  const rows = keys.length
    ? `<ul class="ai-apps-keys">${keys
        .map(
          (k) => `<li><span>${escapeHtml(k.name)} · <code>${escapeHtml(k.masked_key || '')}</code> · ${
            k.last_used_at
              ? escapeHtml(t('aiapps.last_used', 'last used {when}', { when: formatDateTime(k.last_used_at * 1000) }))
              : escapeHtml(t('aiapps.never_used', 'not used yet'))
          }</span> <button type="button" class="btn-pill-toggle is-small" data-ai-app-revoke="${escapeHtml(k.id)}">${escapeHtml(t('aiapps.revoke', 'Revoke'))}</button></li>`,
        )
        .join('')}</ul>`
    : '';
  return `<p class="immich-note">${escapeHtml(
    t('aiapps.desc', 'Apps such as Paperless-ngx, Open WebUI and Home Assistant can use this server\'s chat model and embedder through one OpenAI-compatible address. Give each app its own key; a key can do nothing else.'),
  )}</p>
    <p class="immich-note">${escapeHtml(t('aiapps.address', 'Address'))}: <code>${escapeHtml(data.base_url || '')}</code></p>
    ${rows}
    <form class="immich-form" data-ai-app-create><label>${escapeHtml(t('aiapps.app', 'App'))}<select name="app">${options}</select></label>
      <button type="submit" class="btn-pill-toggle is-primary">${escapeHtml(t('aiapps.create', 'Create a key'))}</button></form>
    <div data-ai-app-result hidden></div>`;
}

export function resultHtml(r) {
  return `<p class="immich-note">${escapeHtml(r.how || '')}</p>
    <p class="immich-note"><strong>${escapeHtml(t('aiapps.once', 'Copy these now: the key is shown only this once.'))}</strong></p>
    <pre class="ai-apps-settings">${escapeHtml(settingsText(r.settings))}</pre>
    <button type="button" class="btn-pill-toggle is-small" data-ai-app-copy>${escapeHtml(t('aiapps.copy', 'Copy settings'))}</button>`;
}

export async function renderAiApps(mount, isAdmin = false) {
  if (!mount) return;
  const card = mount.closest('section') || mount;
  if (!isAdmin) {
    card.hidden = true;
    return;
  }
  let data;
  try {
    data = await api.get('/api/ai/apps');
  } catch (e) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  mount.innerHTML = appsHtml(data);
  mount.querySelector('[data-ai-app-create]')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const r = await api.post('/api/ai/apps/keys', { app: new FormData(e.target).get('app') });
      await renderAiApps(mount, isAdmin);
      const box = mount.querySelector('[data-ai-app-result]');
      if (!box) return;
      box.innerHTML = resultHtml(r);
      box.hidden = false;
      box.querySelector('[data-ai-app-copy]')?.addEventListener('click', () => {
        copyText(settingsText(r.settings)).then(
          () => showToast(t('aiapps.copied', 'Settings copied.'), 'success'),
          () => showToast(t('aiapps.copy_failed', 'Could not copy; select the text instead.'), 'warning'),
        );
      });
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  });
  mount.querySelectorAll('[data-ai-app-revoke]').forEach((btn) => {
    btn.addEventListener('click', () => {
      showConfirmToast(
        t('aiapps.revoke_title', 'Revoke this key?'),
        t('aiapps.revoke_msg', 'The app that uses it stops getting answers until it has a new key.'),
        async () => {
          try {
            await api.delete(`/api/ai/apps/keys/${encodeURIComponent(btn.dataset.aiAppRevoke)}`);
            renderAiApps(mount, isAdmin);
          } catch (err) {
            showToast(err.message || String(err), 'error');
          }
        },
      );
    });
  });
}
