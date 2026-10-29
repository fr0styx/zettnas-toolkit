# Releasing ZettNAS Toolkit

Every release spends three days on the **beta** channel before it reaches **stable**
(OPS-07). Stable users get exactly the image beta users ran: promotion moves tags to the
same signed digest, it never rebuilds.

**Stable is a weekly train** (COMP-10): every Tuesday the newest beta that has had its three
days becomes Stable, so stable users get at most one update a week with one set of dated
notes. Security fixes don't wait for the train (see below).

| Image tag | What it is | Who gets it |
|---|---|---|
| `:edge`, `:main` | every commit on `main` that passes CI | `UPDATE_CHANNEL=edge` |
| `:beta`, `:1.9.3` | the newest version tag, from the moment CI passes | `UPDATE_CHANNEL=beta` |
| `:latest`, `:stable`, `:1.9` | the newest release that finished its soak | `UPDATE_CHANNEL=stable` (default) and Compose files that pin `:latest` |

Each tag also exists with `-core` for the core image.

## Version numbers and changelog entries

- **Patch** (1.9.3 → 1.9.4): fixes only. Nothing a user must do or relearn.
- **Minor** (1.9 → 1.10): anything users must act on (a stricter default, a removed
  option, a changed URL or API) and new features. List the actions under
  "Before you upgrade" in the changelog entry.
- **Changelog headings** are `## vX.Y.Z (date)`, without a channel. A release is a beta
  until promotion marks it Stable on GitHub; the changelog doesn't change when it is
  promoted. A test checks this for entries after v1.9.4.

## Cutting a release

1. Refresh the app catalog's image pins (`python scripts/pin_catalog_images.py`, which writes
   `backend/services/catalog_digests.json`), then update `CHANGELOG.md` and the version, commit, and push a tag such as `v1.9.3`. Only
   repository admins can create `v*` tags, and tags can't be moved or deleted (GitHub
   rulesets).
2. CI builds, scans and signs the images and publishes `:beta` and `:1.9.3`. The GitHub
   release is created as a pre-release named "… (beta)".
3. Run the beta on a real server (Mission Control → Settings → About & Updates → Beta, or
   `UPDATE_CHANNEL=beta`).
4. Every Tuesday (06:00 UTC), the **Promote release** workflow takes the
   newest release that is at least three days old, verifies its image signature, moves
   `:latest`, `:stable` and `:1.9` to it, and marks the GitHub release as the latest, so the
   app's Stable channel offers it. On other days the scheduled run only names the next train
   date in its summary. It warns when nothing has reached Stable for 21 days.

## Stopping a release

Set the repository variable `HOLD_RELEASES` (Settings > Secrets and variables > Actions >
Variables) to the version, for example `v1.9.3`, or to `all`. Promotion skips it and says so
in the workflow summary. Remove the variable to let it continue; fix forward with a new tag.

## Skipping the wait (security fixes)

Actions > **Promote release** > Run workflow: enter the version and tick **skip_soak**. The
same checks run (signature, hold), just without the three days.
