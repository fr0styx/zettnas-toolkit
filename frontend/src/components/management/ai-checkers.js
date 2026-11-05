// The optional reranker in AI settings (AI-13, AI-12): its address and model, saved with one button.
import { api } from '../../api.js';
import { showToast } from '../../toast.js';
import { t } from '../../i18n.js';

const FIELDS = [
  ['ai-rerank-endpoint', 'rerank_endpoint'],
  ['ai-rerank-model', 'rerank_model'],
];

export function bindCheckersForm(root, cfg) {
  const form = root.getElementById('ai-rerank-form');
  if (!form) return;
  const inputs = FIELDS.map(([id, key]) => [root.getElementById(id), key]).filter(([el]) => el);
  for (const [el, key] of inputs) el.value = cfg[key] ?? '';
  if (form.dataset.bound) return;
  form.dataset.bound = '1';
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(inputs.map(([el, key]) => [key, el.value.trim()]));
    try {
      await api.post('/api/ai/config', body);
      showToast(t('ai.rerank_saved', 'Reranker saved'), 'success');
    } catch (err) {
      showToast(t('sso.save_failed', 'Could not save: {error}', { error: err.message }), 'error');
    }
  });
}
