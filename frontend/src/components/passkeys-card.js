/**
 * Your passkeys (RES-3): the card under Two-step sign-in in Users. Add one (this phone, this laptop,
 * a security key), rename it, remove it.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast, showConfirmToast } from '../toast.js';
import { escapeHtml } from '../utils.js';
import { formatDateTime } from '../format.js';
import { addPasskey, passkeysAvailable } from '../passkeys.js';

const when = (ts) => (ts ? formatDateTime(ts * 1000) : t('passkeys.never', 'never'));

/** The card's body: why it may not work here, the list, and the Add button. */
export function passkeysHtml(list, available) {
  const note = available
    ? ''
    : `<p class="usr-xs-muted pk-note">${escapeHtml(t('passkeys.unavailable', 'Passkeys work when Kiboto is opened at its address with a name over https (for example its Tailscale address), not at an IP address.'))}</p>`;
  const rows = list.length
    ? `<ul class="pk-list">${list
        .map(
          (p) => `<li class="pk-item"><span><strong>${escapeHtml(p.name)}</strong>
            <span class="usr-xs-muted">${escapeHtml(t('passkeys.meta', 'for {site} · added {added} · last used {used}', { site: p.rp_id, added: when(p.created_at), used: when(p.last_used_at) }))}</span></span>
            <span class="pk-actions">
              <button type="button" class="btn-pill-toggle is-small" data-pk-rename="${escapeHtml(p.id)}">${escapeHtml(t('passkeys.rename', 'Rename'))}</button>
              <button type="button" class="btn-pill-toggle is-small is-danger" data-pk-remove="${escapeHtml(p.id)}">${escapeHtml(t('passkeys.remove', 'Remove'))}</button>
            </span></li>`,
        )
        .join('')}</ul>`
    : `<p class="usr-xs-muted">${escapeHtml(t('passkeys.none', 'No passkeys yet.'))}</p>`;
  return `${note}${rows}<button type="button" class="btn-save-preset usr-sm" data-pk-add${available ? '' : ' disabled'}>${escapeHtml(t('passkeys.add', 'Add a passkey'))}</button>`;
}

function shell() {
  let card = document.getElementById('passkeys-card');
  if (card) return card;
  const pane = document.getElementById('users-pane-2fa');
  if (!pane) return null;
  card = document.createElement('div');
  card.id = 'passkeys-card';
  card.className = 'drawer-card usr-box';
  card.innerHTML = `<div class="usr-base-bold-strong">${escapeHtml(t('passkeys.title', 'Passkeys'))}</div>
    <div class="usr-xs-muted">${escapeHtml(t('passkeys.desc', 'Sign in with your phone, your laptop\'s fingerprint or face, or a security key: no password to type, nothing to steal. A passkey also counts as the second step.'))}</div>
    <div id="passkeys-body" aria-live="polite">…</div>`;
  const after = document.getElementById('mfa-status-card');
  if (after && after.parentNode === pane) after.after(card);
  else pane.appendChild(card);
  return card;
}

async function render(win = window) {
  const body = document.getElementById('passkeys-body');
  if (!body) return;
  try {
    const { passkeys } = await api.get('/api/auth/passkeys');
    body.innerHTML = passkeysHtml(passkeys || [], passkeysAvailable(win));
  } catch (err) {
    body.textContent = /** @type {Error} */ (err).message || '';
  }
}

/** Loads the card and wires it once. */
export async function loadPasskeysCard(win = window) {
  const card = shell();
  if (!card) return;
  if (!card.dataset.bound) {
    card.dataset.bound = '1';
    card.addEventListener('click', async (e) => {
      const el = /** @type {Element} */ (e.target);
      const add = el.closest('[data-pk-add]');
      const rename = el.closest('[data-pk-rename]');
      const remove = el.closest('[data-pk-remove]');
      try {
        if (add) {
          const name = win.prompt(t('passkeys.name_prompt', 'A name for this passkey (for example "Anna\'s phone")'), '') ?? null;
          if (name === null) return;
          await addPasskey(api, name.trim());
          showToast(t('passkeys.added', 'Passkey added. Next time, choose "Sign in with a passkey".'), 'success');
        } else if (rename) {
          const name = win.prompt(t('passkeys.rename_prompt', 'New name'), '') ?? '';
          if (!name.trim()) return;
          await api.patch(`/api/auth/passkeys/${encodeURIComponent(rename.getAttribute('data-pk-rename') || '')}`, { name: name.trim() });
        } else if (remove) {
          const id = remove.getAttribute('data-pk-remove') || '';
          showConfirmToast(t('passkeys.remove_confirm', 'Remove this passkey? The device stops working for signing in to Kiboto.'), async () => {
            try {
              await api.delete(`/api/auth/passkeys/${encodeURIComponent(id)}`);
            } catch (err) {
              showToast(/** @type {Error} */ (err).message, 'error');
            }
            render(win);
          });
          return;
        } else {
          return;
        }
        render(win);
      } catch (err) {
        const e2 = /** @type {any} */ (err);
        // the person closed the browser's passkey window: nothing to say
        if (e2 && e2.name === 'NotAllowedError') return;
        showToast(e2.message || String(e2), 'error');
      }
    });
  }
  await render(win);
}
