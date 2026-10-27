// "Who can use Zetty": a switch per role, and the log of who asked (B8, backend/services/ai_access.py).
// Kids and guests start off; the superadmin is always on. The log keeps who, when, the model, web
// search and the outcome, never what was asked.
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { html } from '../../html.js';
import { formatDateTime } from '../../format.js';
import { uiCard } from '../../ui/primitives.js';

const CARD_ID = 'ai-access-card';
const LOG_ROWS = 50;

const OUTCOMES = {
  answered: () => t('ai.access_answered', 'Answered'),
  streamed: () => t('ai.access_answered', 'Answered'),
  failed: () => t('ai.access_failed', 'Failed'),
  refused: () => t('ai.access_refused', 'Turned off for them'),
};

const KINDS = {
  chat: () => t('ai.kind_chat', 'Chat'),
  ask: () => t('ai.kind_ask', 'Answer'),
  search: () => t('ai.kind_search', 'Search'),
};

/** One row per role: Ask Zetty and AI search (B11, AI-26). */
export function rolesHtml(roles) {
  return html`<table class="zn-table ai-access-roles"><thead><tr><th></th>
      <th>${t('ai.access_ask', 'Ask Zetty')}</th><th>${t('ai.access_search', 'AI search')}</th></tr></thead>
    <tbody>${roles.map(
      (r) => html`<tr><td>${r.name}${r.locked ? html` <span class="zn-muted">${t('ai.access_always', 'Always on')}</span>` : ''}</td>
        <td><input type="checkbox" role="switch" aria-label="${t('ai.access_ask', 'Ask Zetty')}: ${r.name}" data-ai-role="${r.id}" data-ai-feature="roles" ${r.on ? 'checked' : ''} ${r.locked ? 'disabled' : ''}></td>
        <td><input type="checkbox" role="switch" aria-label="${t('ai.access_search', 'AI search')}: ${r.name}" data-ai-role="${r.id}" data-ai-feature="search_roles" ${r.search !== false ? 'checked' : ''} ${r.locked ? 'disabled' : ''}></td></tr>`,
    )}</tbody></table>`;
}

export function logHtml(rows) {
  if (!rows || !rows.length) return html`<p class="zn-muted">${t('ai.access_log_empty', 'Nobody has asked Zetty yet.')}</p>`;
  return html`<table class="zn-table"><thead><tr>
      <th>${t('ai.access_when', 'When')}</th><th>${t('ai.access_who', 'Who')}</th><th>${t('ai.access_model', 'Model')}</th>
      <th>${t('ai.access_kind', 'What')}</th><th>${t('ai.access_web', 'Web')}</th><th>${t('ai.access_result', 'Result')}</th></tr></thead>
    <tbody>${rows.map(
      (r) => html`<tr><td>${formatDateTime(r.ts * 1000)}</td><td>${r.username} (${r.role})</td><td>${r.model || '—'}</td>
        <td>${(KINDS[r.kind] || (() => r.kind || '—'))()}</td><td>${r.web ? t('ai.access_yes', 'Yes') : t('ai.access_no', 'No')}</td><td>${(OUTCOMES[r.outcome] || (() => r.outcome))()}</td></tr>`,
    )}</tbody></table>`;
}

export function renderAiAccess(card, access, log) {
  const body = html`<p class="zn-muted">${t('ai.access_desc_both', 'Choose which roles may ask Zetty and use AI search. Kids and guests start switched off.')}</p>
    ${rolesHtml(access.roles || [])}
    <details class="ai-access-log"><summary>${t('ai.access_log', 'Who asked Zetty')}</summary>
    <p class="zn-muted">${t('ai.access_log_desc', 'When, who, the model, web search and the result, for {days} days. What was asked is not kept here.', { days: access.log_days || 90 })}</p>
    ${logHtml(log || [])}</details>`;
  card.innerHTML = uiCard({ title: t('ai.access_title', 'Who can use Zetty'), body: String(body), variant: 'boxed' });
  card.querySelectorAll('[data-ai-role]').forEach((sw) => {
    sw.addEventListener('change', async () => {
      sw.disabled = true;
      try {
        const next = await api.put('/api/ai/access', { [sw.dataset.aiFeature || 'roles']: { [sw.dataset.aiRole]: sw.checked } });
        renderAiAccess(card, next, log);
      } catch {
        sw.checked = !sw.checked;
        sw.disabled = false;
      }
    });
  });
}

/** Adds the card under the reranker in AI settings; only for people who may change it. */
export async function installAiAccess(root = document) {
  const anchor = root.getElementById('ai-rerank-form');
  if (!anchor || root.getElementById(CARD_ID)) return;
  const card = document.createElement('div');
  card.id = CARD_ID;
  anchor.insertAdjacentElement('afterend', card);
  try {
    const [access, log] = await Promise.all([
      api.get('/api/ai/access'),
      api.get(`/api/ai/requests?limit=${LOG_ROWS}`).catch(() => ({ requests: [] })),
    ]);
    renderAiAccess(card, access, log.requests || []);
  } catch {
    card.remove(); // not an administrator: the card is not theirs
  }
}
