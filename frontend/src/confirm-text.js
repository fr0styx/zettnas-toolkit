// What the server-required confirmation asks, in the person's language (NUX-2). The server
// sends the action and its target (backend/confirmations.py); its English summary is only the
// fallback for an action this list doesn't know yet.
import { t } from './i18n.js';

// action -> [English title (the button reads like it), English question, destructive]
const ACTIONS = {
  'fs.trash.empty': ['Empty the Recycle Bin', 'Permanently delete everything in every Recycle Bin? This can\'t be undone.', true],
  'storage.pool.create': ['Create the pool', 'Create a storage pool? Everything on the selected disks is erased.', true],
  'storage.pool.delete': ['Delete the pool', 'Delete the storage pool {target}? Its data is lost.', true],
  'storage.snapshot.delete': ['Delete the snapshot', 'Delete the snapshot {target}?', true],
  'storage.snapshot.restore': ['Roll back', 'Roll the pool back to the snapshot {target}? Changes made since then are lost.', true],
  'share.delete': ['Delete the share', 'Delete the share {target}?', true],
  'users.delete': ['Delete the account', 'Delete the account {target}?', true],
  'users.erase_data': ['Erase their data', 'Erase the chats, Zetty log and search data of {target}?', true],
  'users.export_data': ['Download their data', 'Download the chats, Zetty log and search data of {target}? They are told.', false],
  'docker.container.delete': ['Delete the app', 'Delete the container {target}?', true],
  'vm.delete': ['Delete the VM', 'Delete the virtual machine {target}?', true],
  'backup.delete': ['Delete the backup', 'Delete the backup {target}?', true],
  'system.restore': ['Restore settings', 'Restore the system settings from a backup? They replace the current ones.', true],
  'system.reboot': ['Restart the server', 'Restart the server now?', false],
  'system.shutdown': ['Shut down', 'Shut down the server now?', false],
  'updates.apply': ['Update now', 'Update ZettNAS and restart it?', false],
  'updates.revert': ['Go back', 'Go back to the previous version of ZettNAS and its data?', true],
  'ai.index.forget': ['Forget the folder', 'Delete what the AI index learned from this folder?', true],
  'webdav.config': ['Save WebDAV', 'Change who can reach files over WebDAV and which folder it shares?', false],
  'security.rotate_key': ['Replace the key', 'Replace the secret key? Everyone signs in to WebDAV and two-factor again.', true],
  'docker.container.recreate.elevated': ['Give host access', 'Recreate the container {target} with access to the host system?', false],
  'disk.wake': ['Wake the drive', 'Wake the sleeping drive {target}? It spins up now and goes back to sleep on its own later.', false],
  'folder.wake': ['Wake the disk', 'Open {target}? Its disk is asleep: it spins up to show the folder and goes back to sleep on its own later.', false],
  'snapshot.rollback': ['Roll back', 'Put the whole share back as it was in the snapshot {target}? How it is now is kept as a snapshot first.', true],
  'pool.scrub_schedule': ['Check monthly', 'Check the pool {target} for errors once a month? Its disks spin up for the check.', false],
  'security.advisor_fix': ['Apply the fix', 'Apply the Security Advisor fix "{target}"? People may lose access they had before.', false],
};

const key = (action) => action.replace(/[^a-z0-9]+/gi, '_');

/** The confirm dialog for a 428 "confirmation_required" answer: title, message, options. */
export function confirmTextFor(info = {}) {
  const action = String(info.action || '');
  const target = String(info.target || '');
  const known = ACTIONS[action];
  if (!known) {
    const summary = String(info.summary || '').trim();
    return {
      title: t('confirm.title', 'Confirm action'),
      msg: summary ? `${summary}?` : t('confirm.cannot_undo', 'This can\'t be undone. Continue?'),
      options: {},
    };
  }
  const [title, msg, destructive] = known;
  const k = key(action);
  return {
    title: t(`confirm.${k}.title`, title),
    msg: t(`confirm.${k}.msg`, msg, { target }),
    options: { destructive, okText: t(`confirm.${k}.title`, title), allowHtml: false },
  };
}

export const CONFIRM_ACTIONS = ACTIONS;
export const confirmKey = key;
