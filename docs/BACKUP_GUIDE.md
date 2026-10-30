# Backing up your computers to ZettNAS

ZettNAS is a good target for backups of your Macs and PCs. Keep at least one more copy
somewhere else, for example an off-site backup (Backup → Off-site) to a USB disk, another
NAS or a cloud remote: a NAS is one copy, not a backup of itself.

## Mac: Time Machine

**On generic Linux (ZettNAS manages Samba):**

1. In ZettNAS, open **Storage → Shares → New share** and turn on **Enable Apple Time
   Machine Backup**. Set a size limit so backups don't fill the pool (for example
   twice the Mac's disk).
2. Give the Mac's user an account in ZettNAS and access to that share.
3. On the Mac, open Finder → **Go → Connect to Server** and enter
   `smb://<nas-address>/<share>`. Sign in and tick **Remember this password**.
4. Open **System Settings → General → Time Machine → Add Backup Disk** and choose the
   share. Turn on **Encrypt backup**.

**On Unraid:** use Unraid's own share setting (*SMB Security Settings → Export: Yes
(Time Machine)*). Unraid advertises the share, so it appears in Time Machine
directly.

## Windows: File History or Veeam Agent

**File History** (built in, copies your user folders):

1. Create a share for backups in ZettNAS and give your Windows account access.
2. Open **Control Panel → File History → Select drive → Add network location** and
   enter `\\<nas-address>\<share>`.
3. Turn it on and set **Save copies of files** to every hour.

**Veeam Agent for Windows Free** (whole-disk image, recommended if you want to restore a
full PC):

1. Install it and choose **Entire computer** (or volume level).
2. As destination pick **Shared folder** and enter `\\<nas-address>\<share>` with your
   ZettNAS account.
3. Schedule daily backups and keep at least 14 restore points. Create the recovery
   media it offers, so you can restore a PC that no longer boots.

## Linux: restic over SFTP

```bash
restic -r sftp:<user>@<nas-address>:/backups/laptop init
restic -r sftp:<user>@<nas-address>:/backups/laptop backup ~ --exclude ~/.cache
```

Run the backup from a systemd timer or cron, and `restic forget --keep-daily 7
--keep-weekly 4 --prune` once a week.

## Another NAS or a friend: be each other's off-site copy

Install **Backup target (restic REST server)** from the App Catalog on the NAS that keeps the
copy. It is append-only: the sending side can add versions but can't delete or overwrite them,
so ransomware or a mistake there can't wipe the copies. Each account sees only its own folder.
The deploy dialog shows the first account (user `backup` and a generated password); add one per
person with `docker exec -it rest-server create_user <name>`.

On the sending ZettNAS, add an off-site backup (Backup → Off-site) with the destination
`rest:http://<target-address>:8000/backup/` and that user name and password. restic encrypts
everything before it leaves, so the target's owner can't read your files. Over the internet,
reach the target through a VPN such as Tailscale or WireGuard rather than opening port 8000:
the address uses plain HTTP, so the password would otherwise cross the internet unencrypted.

The sender can't prune an append-only target, so ZettNAS notices the refusal after the first
backup, stops asking, and shows that old versions stay there. The target's owner decides how
long to keep them: `--max-size` in the app's `OPTIONS` caps a folder's size.

From any other computer with restic: `restic -r rest:http://<target-address>:8000/<name>/ init`,
with `RESTIC_REST_USERNAME` and `RESTIC_REST_PASSWORD` set.

## A locked cloud copy: nobody can delete it for a while

A cloud bucket with **Object Lock** (Backblaze calls it **File Lock**) keeps every file written
to it for a set number of days. Deleting, by restic, by ransomware or by someone with this
NAS's keys, only hides the newest version; the locked versions stay and can be brought back
until the period ends. It works with Backblaze B2, Wasabi, Amazon S3 and other S3 services.

1. Create the bucket with Object Lock turned on. Most services only allow this when the bucket
   is created; it also turns on versioning.
2. Set a default retention in **Compliance** mode, for example 30 days. Governance mode can be
   lifted by a key with the bypass right, so it protects less.
3. Add a lifecycle rule that removes old (noncurrent or hidden) versions a day after the lock
   ends, or they are kept and billed forever.
4. Add the bucket in Cloud Drives (an `s3` remote, or `b2` for Backblaze) with a key limited to
   that bucket, and add an off-site backup to `rclone:<remote>:<bucket>/zettnas` with the same
   number of days under **Days the bucket locks each copy**.
5. Press **Check the lock**. ZettNAS reads the bucket's settings from the provider and shows
   whether it is locked, in which mode and for how long; the list then shows **Cloud copy
   locked until** the date the newest copy's lock ends.

ZettNAS keeps every version younger than the lock period (pruning them would only hide them)
and prunes the rest as usual. Each backup's new data is locked from the moment it is uploaded,
so the protection covers the last *n* days of backups at any time.

## Two-way sync with a cloud folder

A backup keeps versions; a sync keeps two places the same. **Backup → Two-way sync** pairs a
folder here with a cloud folder (any remote set up in Cloud Drives) and keeps them the same in
both directions, every few hours.

- **Preview first.** A new pair, or one whose folders changed, does nothing until you press
  **Preview** and then **Turn on**. The preview is a dry run listing what would go to the cloud,
  what would come here, what would be deleted and what changed on both sides.
- **The first run only copies.** Files that exist on one side are copied to the other; nothing
  is deleted.
- **Changed on both sides?** Both are kept, as `name..path1` (this NAS) and `name..path2` (the
  cloud). Keep the one you want and delete the other.
- **A mass delete stops it.** If more than a quarter of the files would be deleted (a mistake,
  or ransomware on a PC that syncs into the folder), the run stops, nothing is deleted on the
  other side, and you get an alert; check the preview before turning it on again.
- A sync is not a backup: a file you delete on purpose is deleted on both sides. Keep an
  off-site backup as well.

## Keep a PC or phone in sync with the NAS

For a folder that should be the same on a laptop, a phone and the NAS (not a backup: changes
and deletions go everywhere), install one of these from the **App Catalog**:

- **Syncthing**: peer to peer, no account and nothing in a cloud. Install it, open its page,
  and add the NAS as a device in Syncthing on the PC (Windows, macOS, Linux) or Android phone.
  On the NAS, keep the synced folders under `/data1`. When you install it, **Keep on a share**
  can put `/data1` on a share you already have (say "Family"), so the synced files sit next to
  the rest and Files, SMB and the backups see them; otherwise it is the app's own folder, under
  **App data → syncthing → data1** in Files. A file changed on two devices
  before they met is kept twice, as `name.sync-conflict-<date>-<device>.ext`. Turn on
  **File Versioning** for the folder in Syncthing so a deleted or overwritten file can be
  brought back.
- **Nextcloud**: files plus calendars and contacts, with apps for iPhone and Android and a
  desktop client. Its client keeps a file changed on both sides as `name (conflicted copy).ext`.
  Its files can go on a share the same way, with **Keep on a share** when you install it.

Either way, keep the share in a snapshot schedule or a backup too: a sync passes a mistake on
to every device.

## Protecting the backups themselves

- Use a separate ZettNAS account for backups, not your admin account, and give it
  access to the backup share only.
- Don't map the backup share as a drive letter on Windows: ransomware encrypts mapped
  drives. File History and Veeam connect only while they run.
- Turn on **guard files** in the ransomware guard (Security) so an attack on a share
  freezes writes before it reaches the rest.
- Send a copy off the box: an **off-site backup** (Backup → Off-site) to another NAS or a
  cloud remote, and save its recovery key outside the NAS.
- Where ZettNAS manages the pools itself (ZettOS, plain Linux), **replication** (Storage →
  Replication) copies a ZFS dataset or btrfs subvolume as snapshots to another pool or over
  SSH, sending only what changed. The copy is read-only and keeps the job's last snapshots.
  On TrueNAS use its own Replication Tasks; on Unraid use an off-site backup.


## Disaster recovery: getting ZettNAS itself back

Your files live on the pool; ZettNAS's own settings (users and their passwords and two-factor, shares and their permissions, NFS/SFTP/rclone settings, app stacks, VM definitions) live in its data folder. Keep a copy of those somewhere else:

1. **Schedule a settings backup.** Settings → System → Backups & Recovery → *Backup jobs* → new task → *What to back up: ZettNAS settings*. Pick a folder in the pool (ideally one that is itself copied offsite) or an rclone remote, a frequency, and how many copies to keep. Every copy is encrypted with the passphrase you set.
2. **Keep the passphrase off the server**, in a password manager. Without it a settings backup can't be opened.
3. **If you set an AI data key** (`ZETTNAS_DATA_KEY`), keep a copy with the passphrase. A settings backup holds the encrypted AI chat history as it is; it needs the same key to be read.

To recover on a new install: install ZettNAS with the same `ZETTNAS_DATA_KEY` (if you used one), open Settings → System → Backups & Recovery → *System Configuration Backup & Restore* → *Upload & Restore Archive*, choose the newest `zettnas_backup_*.zettbak` and enter the passphrase. Users, shares and settings come back; the AI index is rebuilt from your files in the background.

## Recover on new hardware

When the NAS itself is gone (stolen, burnt, or the motherboard died), you need two things kept
somewhere else: the **recovery kit** of your off-site backup and, if you made one, the
**settings backup** with its passphrase.

1. **Get your files back first, on any computer.** The recovery kit (Backup → Off-site →
   *Recovery kit*) is a text file with the key, where the backup is, the cloud settings it needs
   and the exact commands. With [restic](https://restic.net) installed:
   ```bash
   export RESTIC_PASSWORD='<the key from the kit>'
   restic -r '<the location from the kit>' snapshots
   restic -r '<the location from the kit>' restore latest --target ./restored
   ```
   For a cloud location, save the kit's `rclone.conf` part to a file, install
   [rclone](https://rclone.org) and run `export RCLONE_CONFIG=./rclone.conf` first.
2. **Install ZettNAS on the new hardware** and create the pool and shares.
3. **Bring the settings back** with *Upload & Restore Archive* (above), using the newest
   settings backup and its passphrase: people, shares and permissions return.
4. **Copy the restored files into the shares**, or point the off-site backup at the same
   location again (same name and key) and use *Versions → Restore*.

The Overview shows "Recovery kit not saved" until each off-site backup's kit has been downloaded
or copied, so nobody finds out on the bad day that the key was only on the NAS.
