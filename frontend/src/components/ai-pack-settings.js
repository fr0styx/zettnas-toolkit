/**
 * The Private AI pack in AI settings (AI-40): what this box gets, install, warm-up, use it.
 * Administrators only.
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { showToast, showConfirmToast } from '../toast.js';

const PRESET_NAMES = { small: 'Small', standard: 'Standard', large: 'Large' };

export function stateText(s) {
  if (s.state === 'ready') return s.in_use ? t('aipack.in_use', 'ZettNAS uses the AI pack.') : t('aipack.state_ready', 'Ready.');
  if (s.state === 'warming') return t('aipack.state_warming', 'Warming up: {phase}. The first start downloads a few GB.', { phase: s.phase || '…' });
  if (s.state === 'stopped') return t('aipack.state_stopped', 'Stopped while idle; it starts again on the next question.');
  if (s.state === 'not-ours') return t('aipack.state_not_ours', "A container named zettnas-ai exists that the AI pack didn't make; it is left alone.");
  return '';
}

export function packHtml(s) {
  const r = s.recommendation || {};
  const b = s.box || {};
  const preset = PRESET_NAMES[r.preset] || r.preset || '';
  const options = Object.entries(PRESET_NAMES)
    .map(([k, v]) => `<option value="${k}"${k === r.preset ? ' selected' : ''}>${escapeHtml(v)}</option>`)
    .join('');
  const facts = `${escapeHtml(String(b.ram_gb ?? '?'))} GB · ${b.gpu ? 'Intel GPU' : 'CPU'}${b.npu ? ' · NPU' : ''}`;
  const install = s.installed || s.state === 'not-ours'
    ? ''
    : `<form class="immich-form" data-ai-pack-install><label>${escapeHtml(t('aiapps.app', 'App'))}<select name="preset">${options}</select></label>
      <button type="submit" class="btn-pill-toggle is-primary">${escapeHtml(t('aipack.install', 'Install the AI pack'))}</button></form>`;
  const use = s.state === 'ready' && !s.in_use
    ? `<button type="button" class="btn-pill-toggle is-primary" data-ai-pack-use>${escapeHtml(t('aipack.use', 'Use it for chat and search'))}</button>`
    : '';
  return `<p class="immich-note">${escapeHtml(t('aipack.desc', "Chat and search on this server's Intel GPU in one OpenVINO Model Server, chosen for its memory. Nothing you set up yourself is changed."))}</p>
    <p class="immich-note">${facts} · ${escapeHtml(t('aipack.recommended', 'Recommended: {preset}, because {why}.', { preset, why: r.why || '' }))}</p>
    ${s.installed || s.state === 'not-ours' ? `<p class="immich-note" data-ai-pack-state>${escapeHtml(stateText(s))}</p>` : ''}
    ${install}${use}`;
}

export async function readInstall(res) {
  // the install answers with one JSON event per line; the last says done or error
  const text = typeof res === 'string' ? res : await res.text();
  const events = text.split('\n').filter(Boolean).map((l) => JSON.parse(l));
  return events[events.length - 1] || {};
}

export async function renderAiPack(mount, isAdmin = false) {
  if (!mount) return;
  const card = mount.closest('section') || mount;
  if (!isAdmin) {
    card.hidden = true;
    return;
  }
  let s;
  try {
    s = await api.get('/api/ai/pack');
  } catch (e) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  mount.innerHTML = packHtml(s);
  mount.querySelector('[data-ai-pack-install]')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector('button');
    if (btn) btn.disabled = true;
    try {
      const res = await api.request('/api/ai/pack/install', { method: 'POST', body: { preset: new FormData(e.target).get('preset') } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const last = await readInstall(res);
      showToast(last.message || '', last.step === 'error' ? 'error' : 'success');
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
    renderAiPack(mount, isAdmin);
  });
  mount.querySelector('[data-ai-pack-use]')?.addEventListener('click', () => {
    showConfirmToast(
      t('aipack.use_title', 'Use the AI pack?'),
      t('aipack.use_msg', 'Chat switches to the pack now. Your files are then re-indexed with its embedder; search keeps working on the old index until that is done.'),
      async () => {
        try {
          const r = await api.post('/api/ai/pack/use', {});
          if (r.reindex) await api.post('/api/ai/reindex', r.reindex);
          showToast(t('aipack.in_use', 'ZettNAS uses the AI pack.'), 'success');
        } catch (err) {
          showToast(err.message || String(err), 'error');
        }
        renderAiPack(mount, isAdmin);
      },
    );
  });
}
