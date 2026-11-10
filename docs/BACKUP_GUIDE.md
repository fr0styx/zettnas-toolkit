# Backing up your computers to Kiboto

Kiboto is a good target for backups of your Macs and PCs. Keep at least one more copy
somewhere else, for example an off-site backup (Backup → Off-site) to a USB disk, another
NAS or a cloud remote: a NAS is one copy, not a backup of itself.

## Mac: Time Machine

**On generic Linux (Kiboto manages Samba):**

1. In Kiboto, open **Storage → Shares → New share** and turn on **Enable Apple Time
   Machine Backup**. Set a size limit so backups don't fill the pool (for example
   twice the Mac's disk).
2. Give the Mac's user an account in Kiboto and access to that share.
3. On the Mac, open Finder → **Go → Connect to Server** and enter
   `smb://<nas-address>/<share>`. Sign in and tick **Remember this password**.
4. Open **System Settings → General → Time Machine → Add Backup Disk** and choose the
   share. Turn on **Encrypt backup**.

**On Unraid:** use Unraid's own share setting (*SMB Security Settings → Export: Yes
(Time Machine)*). Unraid advertises the share, so it appears in Time Machine
directly.

## Windows: File History or Veeam Agent

**File History** (built in, copies your user folders):

1. Create a share for backups in Kiboto and give your Windows account access.
2. Open **Control Panel → File History → Select drive → Add network location** and
   enter `\\<nas-address>\<share>`.
3. Turn it on and set **Save copies of files** to every hour.

**Veeam Agent for Windows Free** (whole-disk image, recommended if you want to restore a
full PC):

1. Install it and choose **Entire computer** (or volume level).
2. As destination pick **Shared folder** and enter `\\<nas-address>\<share>` with your
   Kiboto account.
3. Schedule daily backups and keep at least 14 restore points. Create the recovery
   media it offers, so you can restore a PC that no longer boots.

## Every PC in the house: UrBackup

File History, Veeam and Time Machine each back up one computer and are set up on that
computer. With several PCs, **UrBackup** keeps them all in one place: you see on the NAS
which PC was last backed up, and the schedule, the retention and the restores are managed
there too.

1. In Kiboto, open **Apps → App Catalog**, find **UrBackup (PC backups)** and install it.
   Its backups go to `appdata/urbackup/backups`; move that folder to a share with room if
   your appdata disk is small.
2. Open its web page (port 55414). **First** go to **Settings → Users** and create the
   admin account: until you do, anyone on your network can open the page.
3. Choose **Add new client → Internet client**, give the PC a name and note the server
   address and key it shows. (Inside Docker the server can't find PCs by itself, so each
   PC is added once by hand.)
4. On the PC, install the UrBackup client from urbackup.org, open its settings, turn on
   **Internet mode** and enter the NAS address, port **55415** and that key. Through
   Tailscale the same address works when the laptop is away from home.
5. Under **Settings** pick what to keep. The defaults back up changed files every 5 hours
   and a full disk image every week; on Windows the image can restore a PC that no longer
   starts (make the restore USB stick from urbackup.org once).

UrBackup keeps one copy, on the NAS. Back up the `backups` folder off-site as well
(**Backup → Off-site**), so a dead pool or a fire doesn't take the PCs' backups with it.

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

On the sending Kiboto, add an off-site backup (Backup → Off-site) with the destination
`rest:http://<target-address>:8000/backup/` and that user name and password. restic encrypts
everything before it leaves, so the target's owner can't read your files. Over the internet,
reach the target through a VPN such as Tailscale or WireGuard rather than opening port 8000:
the address uses plain HTTP, so the password would otherwise cross the internet unencrypted.

The sender can't prune an append-only target, so Kiboto notices the refusal after the first
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
   that bucket, and add an off-site backup to `rclone:<remote>:<bucket>/kiboto` with the same
   number of days under **Days the bucket locks each copy**.
5. Press **Check the lock**. Kiboto reads the bucket's settings from the provider and shows
   whether it is locked, in which mode and for how long; the list then shows **Cloud copy
   locked until** the date the newest copy's lock ends.

Kiboto keeps every version younger than the lock period (pruning them would only hide them)
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

- Use a separate Kiboto account for backups, not your admin account, and give it
  access to the backup share only.
- Don't map the backup share as a drive letter on Windows: ransomware encrypts mapped
  drives. File History and Veeam connect only while they run.
- Turn on **guard files** in the ransomware guard (Security) so an attack on a share
  freezes writes before it reaches the rest.
- Send a copy off the box: an **off-site backup** (Backup → Off-site) to another NAS or a
  cloud remote, and save its recovery key outside the NAS.
- Where Kiboto manages the pools itself (ZettOS, plain Linux), **replication** (Storage →
  Replication) copies a ZFS dataset or btrfs subvolume as snapshots to another pool or over
  SSH, sending only what changed. The copy is read-only and keeps the job's last snapshots.
  On TrueNAS use its own Replication Tasks; on Unraid use an off-site backup.


## Disaster recovery: getting Kiboto itself back

Your files live on the pool; Kiboto's own settings (users and their passwords and two-factor, shares and their permissions, NFS/SFTP/rclone settings, app stacks, VM definitions) live in its data folder. Keep a copy of those somewhere else:

1. **Schedule a settings backup.** Settings → System → Backups & Recovery → *Backup jobs* → new task → *What to back up: Kiboto settings*. Pick a folder in the pool (ideally one that is itself copied offsite) or an rclone remote, a frequency, and how many copies to keep. Every copy is encrypted with the passphrase you set.
2. **Keep the passphrase off the server**, in a password manager. Without it a settings backup can't be opened.
3. **If you set an AI data key** (`KIBOTO_DATA_KEY`), keep a copy with the passphrase. A settings backup holds the encrypted AI chat history as it is; it needs the same key to be read.

To recover on a new install: install Kiboto with the same `KIBOTO_DATA_KEY` (if you used one), open Settings → System → Backups & Recovery → *System Configuration Backup & Restore* → *Upload & Restore Archive*, choose the newest `zettnas_backup_*.zettbak` and enter the passphrase. Users, shares and settings come back; the AI index is rebuilt from your files in the background.

## Recover on new hardware

When the NAS itself is gone (stolen, burnt, or the motherboard died), the **recovery kit** of your
off-site backup is enough. Each backup run also stores a copy of Kiboto's settings (people and their
passwords, shares and permissions, apps, VM definitions, the backups themselves and their keys),
encrypted with the backup's recovery key.

1. **Install Kiboto on the new hardware** and create the pool (on Unraid: the array and the shares).
2. **In the setup wizard's first step, choose *Restore from a recovery kit*.** Choose a password for
   now (Kiboto answers nothing else until the first-run password is replaced), then paste the kit or
   pick the saved file. Kiboto connects the backup without writing to it and shows when the settings
   and the files were saved. On a Kiboto that is already set up, the same is in Backup → Off-site →
   *Connect from a recovery kit*.
3. **Bring back the settings.** Kiboto checks them, restarts to apply them (when Docker restarts it by
   itself, as the compose file and the Unraid template set up; otherwise restart the container) and
   asks you to sign in with your **old** password.
4. **Bring back the files**: Backup → Off-site → *Bring back everything* puts every backed-up folder back
   where it was. Files that are already there stay as they are, so it can run again if it stops. It
   shows in Jobs.

A backup made before Kiboto 2.0 has no copy of the settings: use the newest settings backup and its
passphrase with *Upload & Restore Archive* (above) instead, then step 4.

Without a working Kiboto at all, the files still come back on any computer. The kit is a text file
with the key, where the backup is, the cloud settings it needs and the exact commands. With
[restic](https://restic.net) installed:
```bash
export RESTIC_PASSWORD='<the key from the kit>'
restic -r '<the location from the kit>' snapshots
restic -r '<the location from the kit>' restore latest --target ./restored
```
For a cloud location, save the kit's `rclone.conf` part to a file, install [rclone](https://rclone.org)
and run `export RCLONE_CONFIG=./rclone.conf` first.

The Overview shows "Recovery kit not saved" until each off-site backup's kit has been downloaded
or copied, so nobody finds out on the bad day that the key was only on the NAS.

## Back up to another Kiboto box (buddy backups)

Two Kiboto boxes on the same tailnet, at two homes or in two rooms, can keep each other's off-site copy.
Network → File Sharing Services → **Your Kiboto boxes**:

1. On box A, click **Pair this box**. It shows a code (10 minutes, single use) and A's Tailscale address.
2. On box B, type that address and code and click **Pair with that box** (confirmed). Each box now sees
   the other's name, version, free space, how long it has been running and how its backups went,
   nothing else: no files, users or settings. Five wrong codes end the code.
3. On the box that gives space (say A): install **Backup target (restic REST server)** from the App
   Catalog, then tick **Let it back up here** next to B (confirmed).
4. On B: **Back up to this box**, choose the shares, **Set up the backup**. A makes B an account of its
   own on the REST server, and B gets an off-site backup called "Buddy: A" in Backup → Off-site,
   which runs with the others and has its own recovery kit.

B's backups are encrypted with B's key, which A never sees, and A's REST server is append-only: B can
add versions but never delete them, so ransomware on B can't wipe the copies on A. Versions stay on A
until A's owner removes them. **Unpair** on either box tells the other; backups
already made stay where they are. The boxes talk over the tailnet only, so a box on the open internet
can't be paired with.
