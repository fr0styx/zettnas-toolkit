/**
 * The NUT server for the family's PCs (FEAT-11): on or off, the port and monitor user, how many
 * PCs watch the UPS, and the line a PC's upsmon.conf needs.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const c of children) node.append(c);
  return node;
}

/** The card's contents for what /api/ups/nut-server returned. */
export function nutServerBody(info) {
  const box = el('div', { className: 'nut-server-body' });
  box.append(el('div', { className: 'nut-server-title', textContent: t('nut.title', 'UPS for your other computers (NUT server)') }));
  box.append(el('p', { className: 'muted', textContent: t('nut.help', 'PCs with NUT (upsmon, WinNUT or another NUT client) watch this UPS through ZettNAS and shut down when the battery runs low, before the NAS does.') }));
  const toggle = el('input', { type: 'checkbox', name: 'enabled', checked: Boolean(info.enabled) });
  box.append(el('label', { className: 'nut-server-row' }, toggle, ' ', t('nut.enabled', 'Serve the UPS on the home network')));
  const port = el('input', { type: 'number', name: 'port', min: 1, max: 65535, value: String(info.port || 3493) });
  const user = el('input', { type: 'text', name: 'user', maxLength: 32, value: info.user || 'monuser' });
  box.append(el('label', { className: 'nut-server-row' }, t('nut.port', 'Port'), ' ', port));
  box.append(el('label', { className: 'nut-server-row' }, t('nut.user', 'Monitor user'), ' ', user));
  const state = info.enabled
    ? info.running
      ? t('nut.running', 'Running · {n, plural, one {# computer} other {# computers}} watching', { n: info.logins || 0 })
      : t('nut.not_running', 'Turned on but not running (is the port in use?)')
    : t('nut.off', 'Off');
  box.append(el('p', { className: 'nut-server-state', textContent: state }));
  const save = el('button', { type: 'button', className: 'btn-pill-toggle is-small', textContent: t('common.save', 'Save') });
  save.dataset.nut = 'save';
  const show = el('button', { type: 'button', className: 'btn-pill-toggle is-small', textContent: t('nut.show_setup', 'Setup for a PC') });
  show.dataset.nut = 'client';
  const renew = el('button', { type: 'button', className: 'btn-pill-toggle is-small', textContent: t('nut.new_password', 'New password') });
  renew.dataset.nut = 'renew';
  box.append(el('div', { className: 'nut-server-actions' }, save, show, renew));
  box.append(el('pre', { className: 'nut-server-client', hidden: true }));
  return box;
}

export async function renderNutServer(mount) {
  let info;
  try {
    info = await api.get('/api/ups/nut-server');
  } catch (err) {
    mount.textContent = err.message || String(err);
    return;
  }
  mount.replaceChildren(nutServerBody(info));
  mount.onclick = async (e) => {
    const b = e.target.closest('[data-nut]');
    if (!b) return;
    const field = (name) => /** @type {HTMLInputElement} */ (mount.querySelector(`[name="${name}"]`));
    try {
      if (b.dataset.nut === 'client') {
        const c = await api.get('/api/ups/nut-server/client');
        const pre = /** @type {HTMLElement} */ (mount.querySelector('.nut-server-client'));
        pre.textContent = `${t('nut.client_hint', 'In the PC\'s upsmon.conf, with NAS-ADDRESS replaced by the address of this NAS:')}\n${c.upsmon || ''}`;
        pre.hidden = false;
        return;
      }
      const body = b.dataset.nut === 'renew'
        ? { new_password: true }
        : { enabled: field('enabled').checked, port: Number(field('port').value), user: field('user').value.trim() };
      await api.put('/api/ups/nut-server', body);
      showToast(b.dataset.nut === 'renew' ? t('nut.renewed', 'New password made; update it on the PCs.') : t('nut.saved', 'NUT server settings saved.'), 'success');
      renderNutServer(mount);
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  };
}
