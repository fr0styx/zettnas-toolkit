# ADR 0003: Recycle Bin retention on existing installs

- **Status:** Accepted (decision D9 of the v2.0 plan, 27 Oct 2026)
- **Decides:** what the new automatic emptying of the Recycle Bin does to what is already in it

## Context

The Recycle Bin used to keep everything until someone emptied it. The new default empties items
after 30 days and caps the bin's size. Applied as is, the first run after an upgrade would delete
everything that had sat in a bin for longer than that, without anyone having been told.

## Decision

Auto-empty is on everywhere, with a grace period: whatever is already in a bin at the upgrade
counts its 30 days from the upgrade, and the size cap removes nothing older than that before the
grace period ends.

## Consequences

- Nothing disappears on the day of an upgrade; people have a month to look through old items.
- The bin can stay above its size cap for up to 30 days after the upgrade.
