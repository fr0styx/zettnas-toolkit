/**
 * Compression for one share (FEAT-15): what its data uses now, how much it saves where the
 * filesystem reports it (ZFS), and a choice that applies to data written from now on.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { formatNumber } from '../format.js';
import { html } from '../html.js';
import { showToast } from '../toast.js';

/** The words for a setting, e.g. "zstd:3" → "zstd (level 3)". */
export function describeValue(value) {
  if (!value || value === 'off') return t('compress.off', 'Off');
  const [algo, level] = String(value).split(':');
  return level ? t('compress.level', '{algo} (level {level})', { algo, level }) : algo;
}

/** One line about the savings, or '' when the filesystem doesn't report them. */
export function ratioText(ratio) {
  if (!ratio || ratio <= 1) return ratio === 1 ? t('compress.ratio_none', 'Nothing saved yet') : '';
  const saved = Math.round((1 - 1 / ratio) * 100);
  const shown = formatNumber(ratio, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return t('compress.ratio', '{ratio}× smaller on disk (about {saved}% saved)', { ratio: shown, saved });
}

/** The dialog's body for what /api/storage/shares/{name}/compression returned. */
export function compressionBody(name, info) {
  const body = document.createElement('div');
  body.className = 'share-compress';
  const line = (text, cls) => {
    const p = document.createElement('p');
    p.textContent = text;
    if (cls) p.className = cls;
    body.appendChild(p);
  };
  line(t('compress.now', 'Now: {value}', { value: describeValue(info.value) }), 'share-compress-now');
  const ratio = ratioText(info.ratio);
  if (ratio) line(ratio);
  if (info.note) line(info.note, 'muted');
  if (info.asleep) line(t('compress.asleep', 'The disk is asleep, so this shows the pool setting; the folder\'s own setting is read when it is awake.'), 'muted');
  if (!info.supported || info.read_only) {
    line(info.reason || t('compress.unsupported', 'This share\'s filesystem has no compression.'), 'muted');
    return body;
  }
  const form = document.createElement('form');
  form.dataset.compressForm = name;
  const label = document.createElement('label');
  label.textContent = t('compress.choose', 'Compression for new data');
  const select = document.createElement('select');
  select.name = 'value';
  for (const choice of info.choices || []) {
    const opt = document.createElement('option');
    opt.value = choice;
    opt.textContent = describeValue(choice);
    if (choice === String(info.value).split(':')[0] || (choice === 'off' && info.value === 'off')) opt.selected = true;
    select.appendChild(opt);
  }
  label.appendChild(select);
  form.appendChild(label);
  const hint = document.createElement('p');
  hint.className = 'muted';
  hint.textContent = t('compress.hint', 'Files already there keep how they are stored; new and changed files use the new setting. zstd is a good default.');
  form.appendChild(hint);
  const save = document.createElement('button');
  save.type = 'submit';
  save.className = 'btn-pill-toggle';
  save.textContent = t('common.save', 'Save');
  form.appendChild(save);
  body.appendChild(form);
  return body;
}

function dialogHost() {
  let host = document.getElementById('share-compression');
  if (!host) {
    host = document.createElement('div');
    host.id = 'share-compression';
    host.className = 'smart-modal-backdrop';
    host.style.zIndex = '10020';
    host.innerHTML = /** @type {any} */ (html`<div class="smart-modal-window" role="dialog" aria-modal="true" aria-labelledby="share-compression-title">
      <div class="smart-modal-header">
        <span class="smart-modal-title" id="share-compression-title"></span>
        <div class="os-window-controls">
          <button type="button" class="win-btn close-btn" data-close title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
        </div>
      </div>
      <div class="smart-modal-body"></div>
    </div>`);
    document.body.appendChild(host);
    const close = () => {
      host.classList.remove('open');
      host.style.display = 'none';
    };
    host.querySelector('[data-close]').addEventListener('click', close);
    host.addEventListener('click', (e) => {
      if (e.target === host) close();
    });
    host.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') close();
    });
  }
  return host;
}

export async function openShareCompression(name) {
  const host = dialogHost();
  host.querySelector('#share-compression-title').textContent = t('compress.title', 'Compression: {name}', { name });
  const slot = host.querySelector('.smart-modal-body');
  slot.textContent = t('ui.loading', 'Loading...');
  host.style.display = '';
  host.classList.add('open');
  const url = `/api/storage/shares/${encodeURIComponent(name)}/compression`;
  const render = (info) => {
    slot.replaceChildren(compressionBody(name, info));
    const form = slot.querySelector('form');
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const value = /** @type {HTMLSelectElement} */ (form.querySelector('select[name="value"]')).value;
      try {
        render(await api.put(url, { value }));
        showToast(t('compress.saved', 'Compression for {name} is now {value}.', { name, value: describeValue(value) }), 'success');
      } catch (err) {
        showToast(err.message || String(err), 'error');
      }
    });
  };
  try {
    render(await api.get(url));
  } catch (err) {
    slot.textContent = err.message || String(err);
  }
  return host;
}
