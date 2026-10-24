# Backing up your computers to ZettNAS

ZettNAS is a good target for backups of your Macs and PCs. Keep at least one more copy
somewhere else, for example with ZettNAS replication or a cloud remote: a NAS is one
copy, not a backup of itself.

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

## Protecting the backups themselves

- Use a separate ZettNAS account for backups, not your admin account, and give it
  access to the backup share only.
- Don't map the backup share as a drive letter on Windows: ransomware encrypts mapped
  drives. File History and Veeam connect only while they run.
- Turn on **guard files** in the ransomware guard (Security) so an attack on a share
  freezes writes before it reaches the rest.
- Send a copy off the box: **Storage → Replication** to another NAS, or a cloud remote
  under **Remotes**.


## Disaster recovery: getting ZettNAS itself back

Your files live on the pool; ZettNAS's own settings (users and their passwords and two-factor, shares and their permissions, NFS/SFTP/rclone settings, app stacks, VM definitions) live in its data folder. Keep a copy of those somewhere else:

1. **Schedule a settings backup.** Mission Control → System & Identity → *Hyper-Backup Tasks & 3-2-1 Pipelines* → new task → *What to back up: ZettNAS settings*. Pick a folder in the pool (ideally one that is itself copied offsite) or an rclone remote, a frequency, and how many copies to keep. Every copy is encrypted with the passphrase you set.
2. **Keep the passphrase off the server**, in a password manager. Without it a settings backup can't be opened.
3. **If you set an AI data key** (`ZETTNAS_DATA_KEY`), keep a copy with the passphrase. A settings backup holds the encrypted AI chat history as it is; it needs the same key to be read.

To recover on a new install: install ZettNAS with the same `ZETTNAS_DATA_KEY` (if you used one), open Mission Control → System & Identity → *System Configuration Backup & Restore* → *Upload & Restore Archive*, choose the newest `zettnas_backup_*.zettbak` and enter the passphrase. Users, shares and settings come back; the AI index is rebuilt from your files in the background.
