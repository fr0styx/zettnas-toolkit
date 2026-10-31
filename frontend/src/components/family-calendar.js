/**
 * The family calendar and address book (NFEAT-7): where phones find them in the office suite,
 * how to add them on an iPhone and on Android, and, for an office suite installed before they
 * were part of it, a button that adds them.
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

function copyRow(label, value) {
  const code = el('code', { className: 'fc-address', textContent: value });
  const copy = el('button', { type: 'button', className: 'btn-pill-toggle is-small', textContent: t('fc.copy', 'Copy') });
  copy.addEventListener('click', () => {
    Promise.resolve(navigator.clipboard?.writeText(value)).then(
      () => showToast(t('fc.copied', 'Copied.'), 'success'),
      () => showToast(t('fc.copy_failed', "It couldn't be copied: select it and copy it."), 'error'),
    );
  });
  return el('div', { className: 'fc-row' }, el('span', { className: 'fc-label', textContent: label }), code, copy);
}

/** The card's content for what the server says (exported for tests). */
export function familyCalendarBody(info, onAdd) {
  const box = el('div', { className: 'fc-body' });
  if (!info || !info.installed) {
    box.append(el('p', { className: 'invite-meta', textContent: t('fc.none', 'Install the office suite from the App Catalog first; the calendar and contacts come with it.') }));
    return box;
  }
  if (!info.running) {
    box.append(el('p', { className: 'invite-meta', textContent: t('fc.stopped', 'The office suite is stopped. Start it in Apps to sync the calendar and contacts.') }));
    return box;
  }
  box.append(
    copyRow(t('fc.address', 'Address'), info.caldav),
    el('p', { className: 'invite-meta', textContent: t('fc.iphone', 'iPhone and iPad: Settings → Apps → Calendar → Calendar Accounts → Add Account → Other → Add CalDAV Account, server {server}; do the same under Contacts with Add CardDAV Account. Sign in with your ZettNAS name and password.', { server: info.server }) }),
    el('p', { className: 'invite-meta', textContent: t('fc.android', 'Android: install DAVx⁵, choose "Log in with URL and user name" and enter the address above with your ZettNAS name and password.') }),
  );
  const add = el('button', { type: 'button', className: 'btn-pill-toggle is-small', textContent: t('fc.add', 'Add calendar and contacts to the office suite') });
  add.addEventListener('click', () => onAdd(add));
  box.append(el('p', { className: 'invite-meta', textContent: t('fc.add_hint', 'Installed the office suite before they came with it? Add them here.') }), add);
  return box;
}

export async function renderFamilyCalendar(mount) {
  if (!mount) return;
  let info;
  try {
    info = await api.get('/api/docker/catalog/office-suite/family');
  } catch (err) {
    mount.replaceChildren(el('p', { className: 'invite-meta', textContent: err?.message || '' }));
    return;
  }
  const onAdd = async (btn) => {
    btn.disabled = true;
    btn.textContent = t('fc.adding', 'Adding…');
    try {
      const res = await api.post('/api/docker/catalog/office-suite/family', {});
      if (res && res.failed && res.failed.length) showToast(t('fc.add_partly', "Not everything was added: {steps}. Try again in a minute.", { steps: res.failed.join(', ') }), 'warn');
      else showToast(t('fc.added', 'The calendar and contacts are in the office suite.'), 'success');
    } catch (err) {
      showToast(err?.message || '', 'error');
    }
    renderFamilyCalendar(mount);
  };
  mount.replaceChildren(familyCalendarBody(info, onAdd));
}
