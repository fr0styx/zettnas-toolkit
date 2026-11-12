// What the server-required confirmation asks, in the person's language (NUX-2). The server
// sends the action and its target (backend/confirmations.py); its English summary is only the
// fallback for an action this list doesn't know yet.
import { t } from './i18n.js';

// action -> [English title (the button reads like it), English question, destructive]
const ACTIONS = {
  'fs.trash.empty': ['Empty the Recycle Bin', 'Permanently delete everything in every Recycle Bin? This can\'t be undone.', true],
  'storage.pool.create': ['Create the pool', 'Create a storage pool? Everything on the selected disks is erased.', true],
  'storage.pool.delete': ['Delete the pool', 'Delete the storage pool {target}? Its data is lost.', true],
  'storage.pool.erase': ['Delete and erase', 'Delete the storage pool {target} and erase its drives? Everything on them is lost.', true],
  'storage.snapshot.delete': ['Delete the snapshot', 'Delete the snapshot {target}?', true],
  'share.delete': ['Delete the share', 'Delete the share {target}?', true],
  'users.delete': ['Delete the account', 'Delete the account {target}?', true],
  'users.erase_data': ['Erase their data', 'Erase the chats, Kib log and search data of {target}?', true],
  'users.export_data': ['Download their data', 'Download the chats, Kib log and search data of {target}? They are told.', false],
  'docker.container.delete': ['Delete the app', 'Delete the container {target}?', true],
  'vm.delete': ['Delete the VM', 'Delete the virtual machine {target}?', true],
  'vm.restore': ['Restore the backup', 'Restore the backup {target}? The machine’s disks and settings are replaced by the backup’s.', true],
  'backup.delete': ['Delete the backup', 'Delete the backup {target}?', true],
  'system.restore': ['Restore settings', 'Restore the system settings from a backup? They replace the current ones.', true],
  'offsite.restore_all': ['Bring back the files', 'Put every folder of backup {target} back where it was? Files that are already there stay as they are.', false],
  'system.apply_restore': ['Restart and apply', 'Restart Kiboto now and apply the settings backup that is waiting? It replaces people, passwords, two-step sign-in, shares and cloud keys with the ones in it. What was changed since the backup was made is lost. Everyone signs in again.', true],
  'system.reboot': ['Restart the server', 'Restart the server now?', false],
  'system.shutdown': ['Shut down', 'Shut down the server now?', false],
  'updates.apply': ['Update now', 'Update Kiboto and restart it?', false],
  'updates.revert': ['Go back', 'Go back to the previous version of Kiboto and its data?', true],
  'ai.index.forget': ['Forget the folder', 'Delete what the AI index learned from this folder?', true],
  'webdav.config': ['Save WebDAV', 'Change who can reach files over WebDAV and which folder it shares?', false],
  'security.rotate_key': ['Replace the key', 'Replace the secret key? Everyone signs in to WebDAV and two-factor again.', true],
  'docker.container.recreate.elevated': ['Give host access', 'Recreate the container {target} with access to the host system?', false],
  'ai.read_sleeping': ['Read sleeping drives', 'Let Kib read folders on sleeping drives? They spin up for it, now and for every later reading while this is on.', false],
  'disk.wake': ['Wake the drive', 'Wake the sleeping drive {target}? It spins up now and goes back to sleep on its own later.', false],
  'folder.wake': ['Wake the disk', 'Open {target}? Its disk is asleep: it spins up to show the folder and goes back to sleep on its own later.', false],
  'snapshot.rollback': ['Roll back', 'Put the whole share back as it was in the snapshot {target}? How it is now is kept as a snapshot first.', true],
  'share.make_subvolume': ['Make snapshot-ready', 'Make the share {target} snapshot-ready? Its files move into a btrfs subvolume of the same name. Close files on it first: changes saved while it runs may be lost.', true],
  'pool.scrub_schedule': ['Check monthly', 'Check the pool {target} for errors once a month? Its disks spin up for the check.', false],
  'security.advisor_fix': ['Apply the fix', 'Apply the Security Advisor fix "{target}"? People may lose access they had before.', false],
  'hardware.helper': ['Turn on the helper', 'Move the fan and button hardware access into {target}, a small container with no network that alone opens /dev/mem? The next update takes that access away from Kiboto itself.', false],
  'network.nas_name': ['Turn on', 'Let the NAS answer to {target} on the home network? A small helper on the host\'s network does it and only answers name lookups.', false],
  'security.malware_scan': ['Turn on the scan', 'Start ClamAV in {target} to scan files that arrive from outside? It needs about 1.5 GB of memory, briefly up to 3 GB, and downloads its signatures first.', false],
  'security.malware_restore': ['Restore it', 'Put {target} back where it came from although ClamAV flagged it as malware?', true],
  'security.malware_delete': ['Delete it', 'Delete {target} from quarantine for good?', true],
  'users.family_signin': ['Turn on family sign-in', 'Start Pocket ID in {target}, give it an https address in your tailnet and an account for each Kiboto user, so the family can sign in to apps with a passkey?', false],
  'users.family_signin_app': ['Connect the app', 'Let the family sign in to {target} with Pocket ID? A client secret for it is shown once.', false],
  'fleet.pair': ['Pair the boxes', 'Pair with the Kiboto box at {target}? Each box then sees the other\'s name, version, free space and backups.', false],
  'fleet.offer_space': ['Give backup space', 'Let {target} back up to this box? Its backups are append-only and encrypted with its own key; they use space here.', false],
  'network.family_invite': ['Send an invite', 'Invite {target} to reach this NAS from anywhere through their own Tailscale account? They see only this NAS and still sign in to Kiboto.', false],
  'network.publish_app': ['Put it on the internet', 'Put {target} on the internet through Tailscale Funnel? Anyone with its address reaches its own sign-in page; Kiboto\'s page stays private.', true],
  'network.public_links': ['Publish share links', 'Let anyone who has a share link open it from the internet, through Tailscale Funnel on port {target}? Only share links are reachable that way; the rest of the NAS stays private.', false],
  'network.public_links_move_immich': ['Publish and move Immich', 'Publish share links, and move Immich to {target}? Share links need the port Immich’s secure address uses now, and a port on the internet must carry nothing else. Phones and browsers that open Immich at the old address need the new one. If the family signs in to Immich with one account, Kiboto connects it again at the new address and shows the addresses to add in your sign-in provider.'],
  'network.tailscale_install': ['Start Tailscale', 'Start Tailscale in {target}, a container on this NAS’s own network that may change its network settings? Tailscale needs that to connect your devices. Nothing is opened on your router.'],
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
