/**
 * Confirm links (D1): an MCP client asks for an action that changes the NAS, ZettNAS
 * returns /?confirm-action=<id>, and the user decides here.
 */
import { api } from './api.js';
import { t } from './i18n.js';
import { showToast, showConfirmToast } from './toast.js';
import { ZettEventBus } from './event-bus.js';

async function ask(id) {
  const action = await api.get(`/api/ai/actions/${encodeURIComponent(id)}`);
  showConfirmToast(
    t('ai.mcp_confirm_title', 'An assistant wants to make a change'),
    t('ai.mcp_confirm_body', 'Requested through an AI client (MCP): {summary}. Only confirm if you asked for this.', { summary: action.summary }),
    async () => {
      const res = await api.post(`/api/ai/actions/${encodeURIComponent(id)}/confirm`, {});
      const ok = res && !['forbidden', 'blocked', 'error', 'not_found'].includes(res.status);
      showToast(ok ? t('ai.mcp_done', 'Done: {summary}', { summary: action.summary }) : res.error || t('ai.mcp_failed', 'The action did not run.'), ok ? 'success' : 'error');
    },
    null,
    { okText: t('ai.confirm', 'Confirm'), cancelText: t('common.cancel', 'Cancel') }
  );
}

export function initConfirmLink(win = window) {
  const params = new URLSearchParams(win.location.search);
  const id = params.get('confirm-action');
  if (!id) return false;
  params.delete('confirm-action');
  const q = params.toString();
  win.history.replaceState(null, '', win.location.pathname + (q ? `?${q}` : ''));
  ask(id).catch((err) => {
    if (err && err.status === 401) {
      ZettEventBus.on('auth:login', () => ask(id).catch(() => showToast(t('ai.mcp_expired', 'That request expired or belongs to another account.'), 'warn')));
    } else {
      showToast(t('ai.mcp_expired', 'That request expired or belongs to another account.'), 'warn');
    }
  });
  return true;
}
