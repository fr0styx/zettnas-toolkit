/**
 * Model benchmark card in AI → Models (D2).
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { formatDateTime } from '../format.js';

let _poll = null;

function cell(tag, text, cls) {
  const el = document.createElement(tag);
  el.textContent = text;
  if (cls) el.className = cls;
  return el;
}

function placementLabel(p) {
  return { GPU: t('bench.gpu', 'GPU'), split: t('bench.split', 'GPU + CPU'), CPU: t('bench.cpu', 'CPU') }[p] || '—';
}

export async function renderModelBench() {
  const host = document.getElementById('ai-model-bench-card');
  if (!host) return;
  let st;
  try {
    st = await api.get('/api/ai/models/benchmark');
  } catch (e) {
    host.hidden = true; // not an admin, or the AI service is off
    return;
  }
  host.hidden = false;
  const running = st.job && st.job.state === 'running';
  const head = document.createElement('div');
  head.className = 'zn-row zn-row--between';
  head.append(cell('span', t('bench.title', '⏱️ Benchmark installed models'), 'zn-title'));
  const run = cell('button', running ? t('bench.running', 'Running {done} of {total}…', { done: st.job.done || 0, total: st.job.total || '?' }) : t('bench.run', 'Run benchmark'), 'btn-pill-toggle');
  run.type = 'button';
  run.disabled = running;
  run.addEventListener('click', async () => {
    await api.post('/api/ai/models/benchmark', {});
    showToast(t('bench.started', 'Benchmark started. Each model is loaded once, so this can take a few minutes.'), 'info');
    renderModelBench();
  });
  head.append(run);
  const parts = [head, cell('div', t('bench.desc', 'Measures how fast each chat model writes on this NAS and where it runs. "Balanced" is the largest model that still writes at reading speed.'), 'zn-muted')];
  if (st.results && st.results.length) {
    const table = document.createElement('table');
    table.className = 'zn-table';
    const tr = document.createElement('tr');
    [t('bench.model', 'Model'), t('bench.speed', 'Tokens/s'), t('bench.first', 'First token'), t('bench.where', 'Runs on')].forEach((h) => tr.append(cell('th', h)));
    table.append(tr);
    for (const r of st.results) {
      const row = document.createElement('tr');
      row.append(cell('td', r.name));
      row.append(cell('td', r.ok ? String(r.tokens_per_s) : t('bench.failed', 'failed')));
      row.append(cell('td', r.ok ? `${r.first_token_s} s` : '—'));
      row.append(cell('td', r.ok ? placementLabel(r.placement) : (r.error || '').slice(0, 60)));
      table.append(row);
    }
    parts.push(table);
    if (st.finished_at) parts.push(cell('div', t('bench.when', 'Measured {when}', { when: formatDateTime(st.finished_at * 1000) }), 'zn-muted'));
    const rec = st.recommended || {};
    const actions = document.createElement('div');
    actions.className = 'zn-row';
    for (const tier of ['balanced', 'fast']) {
      if (!rec[tier]) continue;
      const b = cell('button', tier === 'balanced' ? t('bench.use_balanced', 'Use balanced: {model}', { model: rec[tier] }) : t('bench.use_fast', 'Use fastest: {model}', { model: rec[tier] }), 'btn-pill-toggle');
      b.type = 'button';
      b.addEventListener('click', async () => {
        const res = await api.post('/api/ai/models/benchmark/apply', { tier });
        showToast(t('bench.applied', 'Ask Zetty now uses {model}', { model: res.active_model }), 'success');
      });
      actions.append(b);
    }
    parts.push(actions);
  }
  host.replaceChildren(...parts);
  clearTimeout(_poll);
  if (running) _poll = setTimeout(renderModelBench, 4000);
}
