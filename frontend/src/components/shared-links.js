/**
 * Links I shared (SET-01): every link a person made, with what it opens, how long it works, and
 * "Stop sharing". An administrator's list holds everyone's links. Links are made in the File
 * Explorer's share dialog; until this list existed they could never be seen or stopped.
 */
import { api } from '../api.js';
import { escapeHtml, copyTextToClipboard } from '../utils.js';
import { showToast, showDangerConfirm } from '../toast.js';
import { t } from '../i18n.js';
import { formatDateTime } from '../format.js';
import { emptyStateHtml } from './empty-state.js';

/** One sentence on whether a link still works. */
export function linkState(link) {
  if (link.is_expired) return t('links.ended', 'Ended');
  if (link.limit_reached) return t('links.used_up', 'All downloads used');
  if (!link.expires_at) return t('links.never_ends', 'Never ends');
  return t('links.until', 'Works until {when}', { when: formatDateTime(link.expires_at * 1000) });
}

function rowHtml(link, me) {
  const upload = link.kind === 'upload';
  const meta = [
    upload ? t('links.kind_upload', 'Send me files') : '',
    linkState(link),
    link.has_password ? t('links.password_yes', 'Password') : t('links.password_no', 'No password'),
    upload
      ? t('links.received', 'Files received: {n}', { n: link.received_count || 0 })
      : t('links.opened', 'Downloads: {n}', { n: link.download_count || 0 }),
    link.created_by && link.created_by !== me ? t('links.by', 'Made by {who}', { who: link.created_by }) : '',
  ].filter(Boolean);
  const name = link.label || link.filename || link.path;
  return `
    <div class="shared-link${link.is_active ? '' : ' is-ended'}" data-token="${escapeHtml(link.token)}">
      <div class="shared-link-what">
        <div class="shared-link-name">${escapeHtml(name)}</div>
        <div class="shared-link-meta">${meta.map(escapeHtml).join(' · ')}</div>
      </div>
      ${link.is_active ? `<button type="button" class="btn-pill-toggle is-small" data-link-copy>${escapeHtml(t('links.copy', 'Copy link'))}</button>` : ''}
      <button type="button" class="btn-pill-toggle is-small is-danger" data-link-stop>${escapeHtml(t('links.stop', 'Stop sharing'))}</button>
    </div>`;
}

/** Draws the list into `mount` and wires its buttons; draws itself again after a stop. */
export async function renderSharedLinks(mount, { me = '' } = {}) {
  if (!mount) return;
  let links;
  try {
    links = await api.get('/api/fs/share-links');
  } catch (err) {
    mount.innerHTML = emptyStateHtml(/** @type {any} */ ({
      title: t('links.load_failed', 'The links could not be loaded.'),
      body: err?.message || '',
      action: { id: 'shared-links-retry', label: t('links.try_again', 'Try again') },
      compact: true,
    }));
    mount.querySelector('#shared-links-retry')?.addEventListener('click', () => renderSharedLinks(mount, { me }));
    return;
  }
  const list = Array.isArray(links) ? links : [];
  if (!list.length) {
    mount.innerHTML = emptyStateHtml(/** @type {any} */ ({
      icon: '🔗',
      title: t('links.empty', 'No shared links.'),
      body: t('links.empty_body', 'A file or folder you share from the File Explorer shows up here.'),
      compact: true,
    }));
    return;
  }
  mount.innerHTML = list.map((link) => rowHtml(link, me)).join('');
  const byToken = Object.fromEntries(list.map((link) => [link.token, link]));
  mount.querySelectorAll('.shared-link').forEach((row) => {
    const link = byToken[row.dataset.token];
    row.querySelector('[data-link-copy]')?.addEventListener('click', () => {
      copyTextToClipboard(link.public_url || `${window.location.origin}${link.url}`);
      showToast(t('toast.link_copied_to_clipboard', 'Link copied to clipboard!'), 'success');
    });
    row.querySelector('[data-link-stop]').addEventListener('click', () => {
      const name = link.label || link.filename || link.path;
      showDangerConfirm(
        t('links.stop', 'Stop sharing'),
        t('links.stop_q', 'Stop sharing “{name}”? The link stops working at once. The file stays where it is.', { name }),
        async () => {
          try {
            await api.delete(`/api/fs/share-links/${encodeURIComponent(link.token)}`);
            showToast(t('links.stopped', 'The link no longer works.'), 'success');
          } catch (err) {
            showToast(err?.message || String(err), 'error');
          }
          renderSharedLinks(mount, { me });
        },
        null,
        { okText: t('links.stop', 'Stop sharing') },
      );
    });
  });
}

/** The list in its own dialog. `everyone` only changes the title: the server decides what a person sees. */
export function openSharedLinks({ everyone = false, me = '' } = {}) {
  document.getElementById('shared-links-modal')?.remove();
  const opener = /** @type {HTMLElement | null} */ (document.activeElement);
  const backdrop = document.createElement('div');
  backdrop.id = 'shared-links-modal';
  backdrop.className = 'smart-modal-backdrop open';
  const title = everyone ? t('links.title_all', 'Links shared from this NAS') : t('links.title', 'Links I shared');
  backdrop.innerHTML = `
    <div class="smart-modal-window shared-links-window" role="dialog" aria-modal="true" aria-labelledby="shared-links-title">
      <div class="smart-modal-header">
        <span class="smart-modal-title" id="shared-links-title"><span aria-hidden="true">🔗</span> ${escapeHtml(title)}</span>
        <div class="os-window-controls">
          <button type="button" id="shared-links-close" class="win-btn close-btn" aria-label="${escapeHtml(t('diagnostics.close_btn', 'Close'))}">✕</button>
        </div>
      </div>
      <div class="smart-modal-body shared-links-list" id="shared-links-list" aria-live="polite"></div>
    </div>`;
  document.body.appendChild(backdrop);
  const close = () => {
    document.removeEventListener('keydown', onKey, true);
    backdrop.remove();
    if (opener && typeof opener.focus === 'function') opener.focus();
  };
  const onKey = (e) => {
    // a question about one link is open on top: Escape belongs to it
    if (e.key === 'Escape' && !document.querySelector('#confirm-toast-modal.open')) {
      e.stopPropagation();
      close();
    }
  };
  document.addEventListener('keydown', onKey, true);
  backdrop.querySelector('#shared-links-close').addEventListener('click', close);
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close(); });
  /** @type {HTMLElement} */ (backdrop.querySelector('#shared-links-close')).focus();
  return renderSharedLinks(backdrop.querySelector('#shared-links-list'), { me });
}
