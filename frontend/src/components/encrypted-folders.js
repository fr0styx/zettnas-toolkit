/**
 * Encrypted folders inside a share (FEAT-13): a list to open and lock them, and for people who
 * manage shares, a form to make one (its recovery key is shown once) or add one back.
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

function button(label, action, extra = {}) {
  const b = el('button', { type: 'button', className: 'btn-pill-toggle is-small', textContent: label, ...extra });
  b.dataset.ef = action;
  return b;
}

function passwordInput(name, label) {
  return el('input', { type: 'password', name, autocomplete: name === 'new' ? 'new-password' : 'current-password', maxLength: 256, placeholder: label, ariaLabel: label });
}

function folderRow(f, canManage) {
  const row = el('div', { className: 'ef-row' });
  row.dataset.name = f.name;
  const state = f.unlocked ? t('ef.open', 'Open') : t('ef.locked', 'Locked');
  row.append(
    el('div', { className: 'ef-name' }, el('strong', { textContent: f.name }), ' ', el('span', { className: `ef-state ef-${f.unlocked ? 'open' : 'locked'}`, textContent: state })),
    el('div', { className: 'ef-where muted', textContent: t('ef.in_share', 'In {share}', { share: f.share }) }),
  );
  const actions = el('div', { className: 'ef-actions' });
  if (f.unlocked) {
    actions.append(button(t('ef.show', 'Show in Files'), 'files'), button(t('ef.lock', 'Lock'), 'lock'));
  } else {
    actions.append(passwordInput('password', t('ef.password', 'Password')), button(t('ef.unlock', 'Open'), 'unlock', { className: 'btn-pill-toggle is-small is-primary' }));
  }
  if (canManage) {
    const keep = el('input', { type: 'checkbox', name: 'keep', checked: !!f.unlock_at_start });
    actions.append(el('label', { className: 'ef-keep' }, keep, ' ', t('ef.keep', 'Open when ZettNAS starts')));
    if (!f.unlocked) actions.append(button(t('ef.forget', 'Take off ZettNAS'), 'forget'));
  }
  row.append(actions);
  return row;
}

function createForm(shares) {
  const form = el('fieldset', { className: 'ef-create' }, el('legend', { textContent: t('ef.new', 'New encrypted folder') }));
  const share = el('select', { name: 'share' });
  for (const s of shares) share.append(el('option', { value: s, textContent: s }));
  form.append(
    el('label', { className: 'ef-field' }, t('ef.share', 'In the share'), ' ', share),
    el('label', { className: 'ef-field' }, t('ef.name', 'Name'), ' ', el('input', { type: 'text', name: 'name', maxLength: 48 })),
    el('label', { className: 'ef-field' }, t('ef.password', 'Password'), ' ', passwordInput('new', t('ef.password', 'Password'))),
    el('label', { className: 'ef-field' }, t('ef.again', 'Password again'), ' ', passwordInput('again', t('ef.again', 'Password again'))),
    el('label', { className: 'ef-keep' }, el('input', { type: 'checkbox', name: 'start' }), ' ', t('ef.keep', 'Open when ZettNAS starts')),
    el('p', { className: 'muted ef-hint', textContent: t('ef.keep_hint', 'Kept open, the password is stored sealed with this server\'s key: anyone who gets the whole server can read the folder. Without it, someone must open it after each restart.') }),
    el('div', { className: 'ef-actions' }, button(t('ef.make', 'Make it'), 'create', { className: 'btn-pill-toggle is-small is-primary' })),
  );
  const adopt = el('details', { className: 'ef-adopt' }, el('summary', { textContent: t('ef.adopt', 'Add back an encrypted folder') }));
  adopt.append(el('p', { className: 'muted ef-hint', textContent: t('ef.adopt_hint', 'Its encrypted files are still in the share (after a reinstall or a restore): give the share, its name and its password.') }));
  adopt.append(button(t('ef.adopt_btn', 'Add it back'), 'adopt'));
  return [form, adopt];
}

function recoveryBox(key) {
  const box = el('div', { className: 'ef-recovery', role: 'alert' });
  box.append(
    el('strong', { textContent: t('ef.recovery_title', 'Save this recovery key now') }),
    el('p', { textContent: t('ef.recovery_desc', 'With it the files can be read even if the password is forgotten. ZettNAS shows it only this once and does not keep it.') }),
    el('code', { className: 'ef-key', textContent: key }),
  );
  const done = button(t('ef.saved', 'I have saved it'), 'saved');
  box.append(el('div', { className: 'ef-actions' }, button(t('ef.copy', 'Copy'), 'copy'), done));
  return box;
}

/** The list of encrypted folders and, for people who manage shares, the form. */
export function encryptedFoldersBody(info) {
  const box = el('div', { className: 'ef-body' });
  if (!info.available) {
    box.append(el('p', { className: 'muted', textContent: t('ef.unavailable', 'This server can\'t open encrypted folders: ZettNAS needs gocryptfs and /dev/fuse.') }));
    return box;
  }
  const list = el('div', { className: 'ef-list' });
  if (!info.folders.length) list.append(el('p', { className: 'muted', textContent: t('ef.none', 'No encrypted folders yet.') }));
  for (const f of info.folders) list.append(folderRow(f, info.can_manage));
  box.append(list);
  if (info.can_manage) {
    if (info.shares.length) box.append(...createForm(info.shares));
    else box.append(el('p', { className: 'muted', textContent: t('ef.no_shares', 'Create a share first: an encrypted folder lives inside one.') }));
  }
  return box;
}

async function act(mount, fn, okText) {
  try {
    const out = await fn();
    if (okText) showToast(okText, 'success');
    return out;
  } catch (err) {
    showToast(err.message, 'error');
    return null;
  } finally {
    if (okText !== undefined) renderEncryptedFolders(mount);
  }
}

function onClick(mount, e) {
  const btn = e.target.closest('[data-ef]');
  if (!btn) return;
  const row = btn.closest('.ef-row');
  const name = row ? row.dataset.name : '';
  const path = (n) => `/api/encrypted-folders/${encodeURIComponent(n)}`;
  const pw = row ? row.querySelector('[name="password"]') : null;
  const action = btn.dataset.ef;
  if (action === 'unlock') act(mount, () => api.post(`${path(name)}/unlock`, { password: pw.value }), t('ef.opened', 'The folder is open.'));
  else if (action === 'lock') act(mount, () => api.post(`${path(name)}/lock`, {}), t('ef.locked_now', 'The folder is locked.'));
  else if (action === 'forget') act(mount, () => api.delete(path(name)), t('ef.forgotten', 'Taken off ZettNAS. Its encrypted files are still in the share.'));
  else if (action === 'files') /** @type {any} */ (window).openFileManager?.(`/mnt/encrypted/${name}`);
  else if (action === 'create' || action === 'adopt') submitForm(mount, action);
  else if (action === 'copy') navigator.clipboard?.writeText(mount.querySelector('.ef-key').textContent).catch(() => {});
  else if (action === 'saved') renderEncryptedFolders(mount);
}

async function submitForm(mount, action) {
  const form = mount.querySelector('.ef-create');
  const value = (n) => form.querySelector(`[name="${n}"]`).value;
  const body = { share: value('share'), name: value('name').trim(), password: value('new') };
  if (action === 'create' && body.password !== value('again')) {
    showToast(t('ef.mismatch', 'The two passwords are not the same.'), 'error');
    return;
  }
  if (action === 'adopt') {
    const out = await act(mount, () => api.post('/api/encrypted-folders/adopt', body), t('ef.added_back', 'The folder is back and open.'));
    return out;
  }
  body.unlock_at_start = form.querySelector('[name="start"]').checked;
  const out = await act(mount, () => api.post('/api/encrypted-folders', body));
  if (out && out.recovery_key) {
    mount.replaceChildren(recoveryBox(out.recovery_key));
  } else if (out) {
    renderEncryptedFolders(mount);
  }
  return out;
}

async function onKeep(mount, e) {
  const box = e.target;
  if (box.name !== 'keep') return;
  const row = box.closest('.ef-row');
  const name = row.dataset.name;
  const url = `/api/encrypted-folders/${encodeURIComponent(name)}/unlock-at-start`;
  if (!box.checked) {
    await act(mount, () => api.put(url, { password: null }), t('ef.keep_off', 'It will stay locked after a restart.'));
    return;
  }
  const pw = row.querySelector('[name="password"]') || row.appendChild(passwordInput('password', t('ef.password', 'Password')));
  if (!pw.value) {
    box.checked = false;
    pw.focus();
    showToast(t('ef.keep_needs', 'Type its password first, then tick the box again.'), 'info');
    return;
  }
  await act(mount, () => api.put(url, { password: pw.value }), t('ef.keep_on', 'It will open when ZettNAS starts.'));
}

export async function renderEncryptedFolders(mount) {
  if (!mount) return;
  let info;
  try {
    info = await api.get('/api/encrypted-folders');
  } catch (err) {
    mount.textContent = err.message;
    return;
  }
  mount.replaceChildren(encryptedFoldersBody(info));
  mount.onclick = (e) => onClick(mount, e);
  mount.onchange = (e) => onKeep(mount, e);
}
