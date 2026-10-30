/**
 * A filter for the kids' devices through AdGuard Home (COMP-13): the AdGuard connection, then
 * per family account its devices (IP, MAC or client ID) and the services blocked for them.
 * Parental control, safe browsing and safe search are always on for a filtered device.
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

const SERVICE_NAMES = {
  tiktok: 'TikTok',
  youtube: 'YouTube',
  instagram: 'Instagram',
  snapchat: 'Snapchat',
  facebook: 'Facebook',
  discord: 'Discord',
  twitch: 'Twitch',
  roblox: 'Roblox',
  fortnite: 'Fortnite',
  steam: 'Steam',
};

/** "192.168.1.20, aa:bb:…" in the field -> the list the API takes. */
export function splitDevices(text) {
  return String(text || '').split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
}

function connectionBox(info) {
  const box = el('fieldset', { className: 'ff-connection' }, el('legend', { textContent: t('ff.connection', 'AdGuard Home') }));
  const url = el('input', { type: 'text', name: 'url', maxLength: 200, value: info.url || 'http://adguardhome:3000' });
  const user = el('input', { type: 'text', name: 'user', maxLength: 64, value: info.user || '', autocomplete: 'off' });
  const pass = el('input', {
    type: 'password',
    name: 'password',
    maxLength: 256,
    autocomplete: 'new-password',
    placeholder: info.has_password ? t('ff.password_kept', 'saved; type to change') : '',
  });
  box.append(el('label', { className: 'ff-row' }, t('ff.url', 'Address'), ' ', url));
  box.append(el('label', { className: 'ff-row' }, t('ff.user', 'AdGuard user'), ' ', user));
  box.append(el('label', { className: 'ff-row' }, t('ff.password', 'AdGuard password'), ' ', pass));
  const save = el('button', { type: 'button', className: 'btn-pill-toggle is-small', textContent: t('common.save', 'Save') });
  save.dataset.ff = 'connect';
  const check = el('button', { type: 'button', className: 'btn-pill-toggle is-small', textContent: t('ff.check', 'Check AdGuard Home') });
  check.dataset.ff = 'check';
  const result = el('p', { className: 'ff-check muted', hidden: true });
  result.setAttribute('role', 'status'); // read out when a check answers (NUX-14)
  box.append(el('div', { className: 'ff-actions' }, save, check), result);
  return box;
}

function personRow(person, saved, services) {
  const row = el('div', { className: 'ff-person' });
  row.dataset.user = person.username;
  row.append(el('div', { className: 'ff-name', textContent: person.display_name || person.username }));
  const devices = el('input', {
    type: 'text',
    name: 'devices',
    value: (saved.devices || []).join(', '),
    placeholder: t('ff.devices_hint', 'IP or MAC addresses of their devices'),
  });
  row.append(el('label', { className: 'ff-row' }, t('ff.devices', 'Devices'), ' ', devices));
  const blocked = el('div', { className: 'ff-services' }, el('span', { textContent: t('ff.block', 'Also block') }));
  for (const s of services) {
    const cb = el('input', { type: 'checkbox', name: 'blocked', value: s, checked: (saved.blocked || []).includes(s) });
    blocked.append(el('label', {}, cb, ' ', SERVICE_NAMES[s] || s));
  }
  row.append(blocked);
  const save = el('button', { type: 'button', className: 'btn-pill-toggle is-small', textContent: t('common.save', 'Save') });
  save.setAttribute('aria-label', t('ff.save_for', 'Save for {name}', { name: person.display_name || person.username }));
  save.dataset.ff = 'person';
  const state = (saved.devices || []).length
    ? t('ff.filtered', '{n, plural, one {# device filtered} other {# devices filtered}}', { n: saved.devices.length })
    : t('ff.not_filtered', 'Not filtered');
  row.append(el('div', { className: 'ff-actions' }, save, el('span', { className: 'muted', textContent: state })));
  return row;
}

/** The card's contents for what /api/family-filter returned. */
export function familyFilterBody(info) {
  const box = el('div', { className: 'ff-body' });
  box.append(connectionBox(info));
  const accounts = info.accounts || [];
  if (!accounts.length) {
    box.append(el('p', { className: 'muted', textContent: t('ff.no_accounts', 'No family or guest accounts yet.') }));
    return box;
  }
  for (const p of accounts) box.append(personRow(p, (info.people || {})[p.username] || {}, info.services || []));
  return box;
}

async function onAction(mount, b) {
  if (b.dataset.ff === 'check') {
    const r = await api.post('/api/family-filter/check');
    const out = /** @type {HTMLElement} */ (mount.querySelector('.ff-check'));
    out.textContent = r.ok ? t('ff.check_ok', 'AdGuard Home {version} answers.', { version: r.version || '' }) : r.error;
    out.hidden = false;
    return;
  }
  if (b.dataset.ff === 'connect') {
    const q = (n) => /** @type {HTMLInputElement} */ (mount.querySelector(`.ff-connection [name="${n}"]`)).value;
    const body = { url: q('url').trim(), user: q('user').trim() };
    if (q('password')) body.password = q('password');
    await api.put('/api/family-filter/connection', body);
    showToast(t('ff.connection_saved', 'AdGuard Home connection saved.'), 'success');
  } else {
    const row = /** @type {HTMLElement} */ (b.closest('.ff-person'));
    const devices = splitDevices(/** @type {HTMLInputElement} */ (row.querySelector('[name="devices"]')).value);
    const blocked = [...row.querySelectorAll('input[name="blocked"]')]
      .filter((c) => /** @type {HTMLInputElement} */ (c).checked)
      .map((c) => /** @type {HTMLInputElement} */ (c).value);
    await api.put(`/api/family-filter/people/${encodeURIComponent(row.dataset.user || '')}`, { devices, blocked });
    showToast(devices.length ? t('ff.person_saved', 'Their devices are filtered now.') : t('ff.person_cleared', 'Their devices are no longer filtered.'), 'success');
  }
  renderFamilyFilter(mount);
}

export async function renderFamilyFilter(mount) {
  if (!mount) return;
  let info;
  try {
    info = await api.get('/api/family-filter');
  } catch (err) {
    showLoadError(mount, err, () => renderFamilyFilter(mount));
    return;
  }
  mount.replaceChildren(familyFilterBody(info));
  mount.onclick = async (e) => {
    const b = /** @type {HTMLElement} */ (e.target).closest('[data-ff]');
    if (!(b instanceof HTMLElement)) return;
    try {
      await onAction(mount, b);
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  };
}
