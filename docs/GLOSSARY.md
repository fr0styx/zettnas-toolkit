# Naming glossary

One name for each job, used the same way in the interface, the docs and the API descriptions.
Reviews check new text against this list; `tests/test_glossary.py` fails when a retired name comes
back in text people read.

| Use | Not | What it is |
|---|---|---|
| **Backups**, backup job | Hyper-Backup, 3-2-1 pipeline | Copies of your files or settings kept somewhere else, on a schedule |
| **Snapshots** | checkpoints (for shares) | Read-only point-in-time copies of a share on the same disks |
| **Previous versions** | — | Earlier copies of one file, taken from its snapshots |
| **Recycle Bin** | Trash, System Trash | Where deleted files wait until the bin is emptied |
| **Apps** | Containers, Docker (in everyday text) | Programs installed from the app catalog |
| **Ask Zetty** | Chatbot, ZettAI Studio, NAS Copilot | The chat that answers questions about your files and your server |
| **AI search** | RAG, knowledge engine (in everyday text) | Finding files by what is in them |
| **Settings** | Mission Control (in new text) | The window where the server is set up |
| **Drives** | disks, devices (in everyday text) | The physical drives in or attached to the server |
| **Shares** | network shares, SMB shares (in everyday text) | Folders other computers and phones can open |

Technical words (SMB, NFS, RAID, Docker, ports) belong in help text and Advanced sections, not in
titles, buttons or the first sentence of a message.

Retired names that the test enforces today: `Hyper-Backup`. The others in the "Not" column move
to the enforced list as the copy pass reaches them.
