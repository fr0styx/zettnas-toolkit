/**
 * Encrypted folders inside a share (FEAT-13): a list to open and lock them, and for people who
 * manage shares, a form to make one (its recovery key is shown once) or add one back.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showLoadError } from './load-error.js';
import { showConfirmToast, showToast } from '../toast.js';

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

/** A labelled field: the label is visible, not only a placeholder (NUX-11). */
function field(label, input) {
  return el('label', { className: 'ef-field' }, label, ' ', input);
}

function folderRow(f, canManage) {
  const row = el('div', { className: 'ef-row' });
  row.dataset.name = f.name;
  // the state says "Unlocked", the button "Unlock": not one word for both (NUX-11)
  const state = f.unlocked ? t('ef.state_unlocked', 'Unlocked') : t('ef.locked', 'Locked');
  row.append(
    el('div', { className: 'ef-name' }, el('strong', { textContent: f.name }), ' ', el('span', { className: `ef-state ef-${f.unlocked ? 'open' : 'locked'}`, textContent: state })),
    el('div', { className: 'ef-where muted', textContent: t('ef.in_share', 'In {share}', { share: f.share }) }),
  );
  const actions = el('div', { className: 'ef-actions' });
  if (f.unlocked) {
    actions.append(button(t('ef.show', 'Show in Files'), 'files'), button(t('ef.lock', 'Lock'), 'lock'));
  } else {
    // a form, so Enter in its one password field unlocks; the button itself is a plain button
    const open = el('form', { className: 'ef-unlock' });
    open.dataset.efForm = 'unlock';
    const go = button(t('ef.unlock_btn', 'Unlock'), 'unlock', { className: 'btn-pill-toggle is-small is-primary' });
    open.append(field(t('ef.password', 'Password'), passwordInput('password', t('ef.password', 'Password'))), go);
    actions.append(open);
  }
  if (canManage) {
    const keep = el('input', { type: 'checkbox', name: 'keep', checked: !!f.unlock_at_start });
    actions.append(el('label', { className: 'ef-keep' }, keep, ' ', t('ef.keep', 'Open when ZettNAS starts')));
    if (!f.unlocked) actions.append(button(t('ef.remove', 'Remove from the list'), 'forget'));
  }
  row.append(actions);
  return row;
}

function createForm(shares) {
  const form = el('fieldset', { className: 'ef-create' }, el('legend', { textContent: t('ef.new', 'New encrypted folder') }));
  const share = el('select', { name: 'share' });
  for (const s of shares) share.append(el('option', { value: s, textContent: s }));
  form.append(
    field(t('ef.share', 'In the share'), share),
    field(t('ef.name', 'Name'), el('input', { type: 'text', name: 'name', maxLength: 48, placeholder: t('ef.name_hint', 'Letters, digits and spaces, in any language') })),
    field(t('ef.password', 'Password'), passwordInput('new', t('ef.password', 'Password'))),
    field(t('ef.again', 'Password again'), passwordInput('again', t('ef.again', 'Password again'))),
    el('label', { className: 'ef-keep' }, el('input', { type: 'checkbox', name: 'start' }), ' ', t('ef.keep', 'Open when ZettNAS starts')),
    el('p', { className: 'muted ef-hint', textContent: t('ef.keep_hint', 'Kept open, the password is stored sealed with this server\'s key: anyone who gets the whole server can read the folder. Without it, someone must open it after each restart.') }),
    el('div', { className: 'ef-actions' }, button(t('ef.make', 'Make it'), 'create', { className: 'btn-pill-toggle is-small is-primary' })),
  );
  // its own fields: adding a folder back needs its password once, not a new one twice (NUX-11)
  const adopt = el('details', { className: 'ef-adopt' }, el('summary', { textContent: t('ef.adopt', 'Add back an encrypted folder') }));
  const adoptShare = el('select', { name: 'share' });
  for (const s of shares) adoptShare.append(el('option', { value: s, textContent: s }));
  adopt.append(
    el('p', { className: 'muted ef-hint', textContent: t('ef.adopt_hint', 'Its encrypted files are still in the share (after a reinstall or a restore): give the share, its name and its password.') }),
    field(t('ef.share', 'In the share'), adoptShare),
    field(t('ef.name', 'Name'), el('input', { type: 'text', name: 'name', maxLength: 48 })),
    field(t('ef.password', 'Password'), passwordInput('password', t('ef.password', 'Password'))),
    el('div', { className: 'ef-actions' }, button(t('ef.adopt_btn', 'Add it back'), 'adopt')),
  );
  return [form, adopt];
}

function recoveryBox(key, name = '') {
  const box = el('div', { className: 'ef-recovery', role: 'alert' });
  const code = el('code', { className: 'ef-key', textContent: key, tabIndex: -1 });
  box.dataset.folder = name;
  box.append(
    el('strong', { textContent: t('ef.recovery_title', 'Save this recovery key now') }),
    el('p', { textContent: t('ef.recovery_desc', 'With it the files can be read even if the password is forgotten. ZettNAS shows it only this once and does not keep it.') }),
    code,
  );
  const done = button(t('ef.saved', 'I have saved it'), 'saved');
  box.append(el('div', { className: 'ef-actions' }, button(t('ef.copy', 'Copy'), 'copy'), button(t('ef.download', 'Download as a file'), 'download'), done));
  return box;
}

// While the key is on screen, leaving the page asks first (NUX-11)
function askBeforeLeaving(e) {
  e.preventDefault();
  e.returnValue = '';
}

export function holdKey(on) {
  window.removeEventListener('beforeunload', askBeforeLeaving);
  if (on) window.addEventListener('beforeunload', askBeforeLeaving);
}

function downloadKey(mount) {
  const box = mount.querySelector('.ef-recovery');
  const key = mount.querySelector('.ef-key').textContent;
  const text = `${t('ef.file_head', 'ZettNAS encrypted folder recovery key')}: ${box?.dataset.folder || ''}\n\n${key}\n`;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
  a.download = `zettnas-recovery-key-${(box?.dataset.folder || 'folder').replace(/[^\p{L}\p{N}_-]+/gu, '-')}.txt`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/** The list of encrypted folders and, for people who manage shares, the form. */
export function encryptedFoldersBody(info) {
  const box = el('div', { className: 'ef-body' });
  if (!info.available) {
    box.append(el('p', { className: 'muted', title: 'gocryptfs, /dev/fuse', textContent: t('ef.unavailable_plain', 'This server can\'t open encrypted folders: the tool that encrypts them isn\'t available here. The person who manages ZettNAS can find the details in its documentation.') }));
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
  else if (action === 'forget') {
    showConfirmToast(
      t('ef.remove_title', 'Remove {name} from the list', { name }),
      t('ef.remove_msg', 'ZettNAS stops showing {name}. Its encrypted files stay in the share, and you can add it back later with its password.', { name }),
      () => act(mount, () => api.delete(path(name)), t('ef.forgotten', 'Taken off ZettNAS. Its encrypted files are still in the share.')),
      null,
      { allowHtml: false },
    );
  }
  else if (action === 'files') /** @type {any} */ (window).openFileManager?.(`/mnt/encrypted/${name}`);
  else if (action === 'create' || action === 'adopt') submitForm(mount, action);
  else if (action === 'copy') {
    const write = navigator.clipboard?.writeText(mount.querySelector('.ef-key').textContent);
    Promise.resolve(write || Promise.reject(new Error('no clipboard'))).then(
      () => showToast(t('ef.copied', 'The recovery key is copied. Paste it somewhere safe, away from this server.'), 'success'),
      () => showToast(t('ef.copy_failed', "It couldn't be copied: select the key and copy it, or download it as a file."), 'error'),
    );
  } else if (action === 'download') downloadKey(mount);
  else if (action === 'saved') {
    showConfirmToast(
      t('ef.saved_title', 'Is the recovery key saved?'),
      t('ef.saved_msg', 'ZettNAS won\'t show it again. Without it and the password, nobody can read this folder.'),
      () => {
        holdKey(false);
        renderEncryptedFolders(mount);
      },
      null,
      { okText: t('ef.saved_yes', 'Yes, it is saved'), allowHtml: false },
    );
  }
}

async function submitForm(mount, action) {
  if (action === 'adopt') {
    const box = mount.querySelector('.ef-adopt');
    const v = (n) => box.querySelector(`[name="${n}"]`).value;
    const body = { share: v('share'), name: v('name').trim(), password: v('password') };
    return act(mount, () => api.post('/api/encrypted-folders/adopt', body), t('ef.added_back', 'The folder is back and open.'));
  }
  const form = mount.querySelector('.ef-create');
  const value = (n) => form.querySelector(`[name="${n}"]`).value;
  const body = { share: value('share'), name: value('name').trim(), password: value('new') };
  if (body.password !== value('again')) {
    showToast(t('ef.mismatch', 'The two passwords are not the same.'), 'error');
    return;
  }
  body.unlock_at_start = form.querySelector('[name="start"]').checked;
  const out = await act(mount, () => api.post('/api/encrypted-folders', body));
  if (out && out.recovery_key) {
    mount.replaceChildren(recoveryBox(out.recovery_key, body.name));
    holdKey(true);
    /** @type {HTMLElement} */ (mount.querySelector('.ef-key')).focus(); // read out, and easy to select
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
    showLoadError(mount, err, () => renderEncryptedFolders(mount));
    return;
  }
  mount.replaceChildren(encryptedFoldersBody(info));
  mount.onclick = (e) => onClick(mount, e);
  mount.onchange = (e) => onKeep(mount, e);
  mount.onsubmit = (e) => {
    const form = /** @type {HTMLElement} */ (e.target).closest('[data-ef-form="unlock"]');
    if (!form) return;
    e.preventDefault();
    const row = /** @type {HTMLElement} */ (form.closest('.ef-row'));
    const pw = /** @type {HTMLInputElement} */ (form.querySelector('[name="password"]'));
    act(mount, () => api.post(`/api/encrypted-folders/${encodeURIComponent(row.dataset.name)}/unlock`, { password: pw.value }), t('ef.opened', 'The folder is open.'));
  };
}
