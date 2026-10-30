/**
 * Camera alerts from Frigate (COMP-11): on or off, Frigate's address, which objects, which
 * cameras, how sure and how often. Frigate itself comes from the App Catalog.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showLoadError } from './load-error.js';
import { showToast } from '../toast.js';

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const c of children) node.append(c);
  return node;
}

const LABEL_NAMES = () => ({
  person: t('frigate.l_person', 'People'),
  car: t('frigate.l_car', 'Cars'),
  dog: t('frigate.l_dog', 'Dogs'),
  cat: t('frigate.l_cat', 'Cats'),
  bicycle: t('frigate.l_bicycle', 'Bicycles'),
  motorcycle: t('frigate.l_motorcycle', 'Motorcycles'),
  bird: t('frigate.l_bird', 'Birds'),
});

/** One line saying whether it runs and when Frigate last answered. */
/** One checkbox per camera Frigate reports; the text field follows them (empty = every camera). */
export function cameraChoices(mount, names) {
  const box = /** @type {HTMLElement | null} */ (mount.querySelector('.frigate-cams'));
  const field = /** @type {HTMLInputElement | null} */ (mount.querySelector('[name="cameras"]'));
  if (!box || !field || !(names || []).length) return;
  const chosen = field.value.split(',').map((s) => s.trim()).filter(Boolean);
  const sync = () => {
    const ticked = [...box.querySelectorAll('input:checked')].map((c) => /** @type {HTMLInputElement} */ (c).value);
    field.value = ticked.length === names.length ? '' : ticked.join(', ');
  };
  box.replaceChildren(...names.map((n) => {
    const cb = el('input', { type: 'checkbox', value: n, checked: !chosen.length || chosen.includes(n) });
    cb.addEventListener('change', sync);
    return el('label', {}, cb, ' ', n);
  }));
  field.closest('label')?.setAttribute('hidden', '');
}

export function stateText(info, now = Date.now() / 1000) {
  if (!info.enabled) return t('frigate.off', 'Off');
  if (info.last_error) return info.last_error;
  if (!info.last_check) return t('frigate.waiting', 'On; the first look is within a minute');
  const mins = Math.max(0, Math.round((now - info.last_check) / 60));
  return t('frigate.checked', 'On · Frigate last checked {n, plural, =0 {just now} one {# minute ago} other {# minutes ago}}', { n: mins });
}

/** The card's contents for what /api/notifications/frigate returned. */
export function frigateBody(info) {
  const box = el('div', { className: 'frigate-body' });
  const enabled = el('input', { type: 'checkbox', name: 'enabled', checked: Boolean(info.enabled) });
  box.append(el('label', { className: 'frigate-row' }, enabled, ' ', t('frigate.enabled', 'Send what Frigate sees as camera alerts')));
  const url = el('input', { type: 'text', name: 'url', maxLength: 200, value: info.url || 'http://frigate:5000' });
  box.append(el('label', { className: 'frigate-row' }, t('frigate.url', "Frigate's address"), ' ', url));
  const names = LABEL_NAMES();
  const labels = el('fieldset', { className: 'frigate-labels' }, el('legend', { textContent: t('frigate.labels', 'Alert me about') }));
  for (const l of info.choices || Object.keys(names)) {
    const cb = el('input', { type: 'checkbox', name: 'label', value: l, checked: (info.labels || []).includes(l) });
    labels.append(el('label', {}, cb, ' ', names[l] || l));
  }
  box.append(labels);
  const cams = el('input', { type: 'text', name: 'cameras', value: (info.cameras || []).join(', '), placeholder: t('frigate.all_cameras', 'all cameras') });
  box.append(el('label', { className: 'frigate-row' }, t('frigate.cameras', 'Cameras'), ' ', cams));
  box.append(el('div', { className: 'frigate-cams' })); // checkboxes once Frigate has named its cameras (NUX-12)
  const score = el('input', { type: 'number', name: 'min_score', min: 30, max: 99, value: String(Math.round((info.min_score || 0.7) * 100)) });
  box.append(el('label', { className: 'frigate-row' }, t('frigate.min_score', 'Only when at least this sure (%)'), ' ', score));
  const cool = el('input', { type: 'number', name: 'cooldown_min', min: 1, max: 240, value: String(info.cooldown_min || 5) });
  box.append(el('label', { className: 'frigate-row' }, t('frigate.cooldown', 'Quiet minutes after an alert, per camera and object'), ' ', cool));
  box.append(el('p', { className: 'frigate-state', textContent: stateText(info) }));
  const save = el('button', { type: 'button', className: 'btn-pill-toggle is-small', textContent: t('common.save', 'Save') });
  save.dataset.frigate = 'save';
  const test = el('button', { type: 'button', className: 'btn-pill-toggle is-small', textContent: t('frigate.test', 'Check Frigate') });
  test.dataset.frigate = 'test';
  box.append(el('div', { className: 'frigate-actions' }, save, test));
  const result = el('p', { className: 'frigate-test muted', hidden: true });
  result.setAttribute('role', 'status'); // read out when a check answers (NUX-14)
  box.append(result);
  return box;
}

/** The PUT body from the card's fields. */
export function readForm(mount) {
  const q = (name) => /** @type {HTMLInputElement} */ (mount.querySelector(`[name="${name}"]`));
  const labels = [...mount.querySelectorAll('input[name="label"]')]
    .filter((c) => /** @type {HTMLInputElement} */ (c).checked)
    .map((c) => /** @type {HTMLInputElement} */ (c).value);
  const cameras = q('cameras').value.split(',').map((s) => s.trim()).filter(Boolean);
  return {
    enabled: q('enabled').checked,
    url: q('url').value.trim(),
    labels,
    cameras,
    min_score: Number(q('min_score').value) / 100,
    cooldown_min: Number(q('cooldown_min').value),
  };
}

export async function renderFrigateEvents(mount) {
  if (!mount) return;
  let info;
  try {
    info = await api.get('/api/notifications/frigate');
  } catch (err) {
    showLoadError(mount, err, () => renderFrigateEvents(mount));
    return;
  }
  mount.replaceChildren(frigateBody(info));
  mount.onclick = async (e) => {
    const b = /** @type {HTMLElement} */ (e.target).closest('[data-frigate]');
    if (!(b instanceof HTMLElement)) return;
    try {
      if (b.dataset.frigate === 'test') {
        const r = await api.post('/api/notifications/frigate/test');
        const out = /** @type {HTMLElement} */ (mount.querySelector('.frigate-test'));
        out.textContent = r.ok
          ? t('frigate.test_ok', 'Frigate {version} answers, {n, plural, one {# camera} other {# cameras}}: {names}', {
            version: r.version || '',
            n: (r.cameras || []).length,
            names: (r.cameras || []).join(', ') || '–',
          })
          : r.error;
        out.hidden = false;
        if (r.ok) cameraChoices(mount, r.cameras || []);
        return;
      }
      await api.put('/api/notifications/frigate', readForm(mount));
      showToast(t('frigate.saved', 'Camera alert settings saved.'), 'success');
      renderFrigateEvents(mount);
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  };
}
