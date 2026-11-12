# Privacy and data flow

Kiboto runs on your hardware. This page lists everything it sends off the NAS, and when.
If something here is wrong, please open an issue.

## Stays on the NAS

- Your files, the search index (`rag_index.db`) and AI conversations. The index and the
  conversations are encrypted when the install has a data key (`KIBOTO_DATA_KEY`, see
  [Installation](INSTALLATION.md)); without one they are plain files on the NAS.
- Questions you ask Ask Kib and the answers, when the chat model runs on this NAS
  (Ollama or OpenVINO Model Server). Kiboto looks for AI runtimes by the names `ollama` and
  `ovms` on this machine or its Docker network, or uses the chat address set for Kib; it never
  tries your router or other machines by address. A machine on your network that answers to the
  name `ollama` or `ovms` would be used.
- Photos sent for captions and text reading. They go to the vision model on this NAS,
  at most 896 pixels on the long side (scanned PDF pages up to 1600), and nowhere else unless
  you set a server for photo search (below).
- Hardware readings, logs and settings, and the file activity log (who changed which file,
  kept 90 days).
- The event log: alerts, finished and failed backups, power, app and hardware events, kept 90
  days. Everyone who may view the system reads it, so it holds no file names, no camera alerts
  and no sign-ins; when the malware scan moves a file to quarantine it names the threat, not
  the file. Which entries you have seen is saved with your account. **Export my data** includes
  the entries that name you, and erasing an account replaces its name in them with a pseudonym.

Kiboto has no analytics and does not phone home. The one exception is the anonymous weekly
health report below, which is off unless you turn it on.

## Leaves the NAS only when you use the feature

| Feature | Goes to | What is sent | When |
|---|---|---|---|
| Ask Kib web search | DuckDuckGo (duckduckgo.com, html.duckduckgo.com, api.duckduckgo.com), Wikipedia (en.wikipedia.org), and a page whose link you typed (found pages are not opened) | at most the first 200 characters of your question (or search words from it) | while **Web** is on. The switch is remembered in your browser, so it stays on for later chats until you turn it off. The Kid and Guest roles never use the web. The answer lists the services used |
| Ask Kib weather | wttr.in | a place name you typed | same as above |
| Immich connection | the Immich server you connect | your search text and your Immich key | when you search with Immich connected |
| Second check of search results (reranker) | the address you set | your search text and excerpts of the matching files | on each search, if you set one |
| Speech to text | the speech server you set | what you dictate | when you dictate, if you set one |
| Find photos by what is in them | the photo server you set | a small copy of every photo | when photos are read, if you set one |
| Model that reads your files, on another machine | the address you set for it | text from your files, and your searches | when files are read and searched, if you set one |
| Desktop weather widget | api.open-meteo.com and geocoding-api.open-meteo.com (from your browser) | city name, then its coordinates | while the widget is on the desktop |
| Calendar holidays | date.nager.at (from your browser) | year and country code | when the calendar shows public holidays |
| Update check | api.github.com, ghcr.io | your IP address and the version request | when you open **Updates** |
| Container image updates | the registries your containers come from (e.g. Docker Hub at index.docker.io, ghcr.io) | image names | when you check for or apply container updates |
| App catalog | github.com / raw.githubusercontent.com and the catalog sources you add | template requests | when you open or refresh the catalog |
| App logos in the catalog | cdn.jsdelivr.net (the dashboard-icons set) or raw.githubusercontent.com, asked by Kiboto, never by your browser | the logo's address | once per logo; Kiboto keeps a copy, and logos from any other host aren't shown |
| Model search and install | huggingface.co, the Ollama registry | model names you search for or install | when you search for or install a model |
| VM installer images | the OS vendor download servers: old-releases.ubuntu.com, cdimage.debian.org, archives.fedoraproject.org, fedorapeople.org (Windows drivers), dl-cdn.alpinelinux.org, download.sys.truenas.net, software-download.microsoft.com | the download request | when you download an ISO from the VM catalog |
| Notifications | the services you set up (ntfy.sh, Slack, Discord, email, Telegram), or an address on your own network such as Home Assistant or Gotify (never this NAS itself or a cloud metadata address) | the alert text | when an alert fires |
| Phone notifications (Web Push) | the push service of the phone's browser maker (Google, Mozilla, Apple or Microsoft) | the alert, encrypted for that phone: the push service sees only ciphertext and when it was sent | when an alert fires, to phones where you turned notifications on |
| Cloud remotes and backups | the providers you connect (S3, B2, OneDrive, Google Drive, …) | the files you choose to sync | as you configure |
| Locked cloud copy check | Backblaze (api.backblazeb2.com and the API address it returns), or the S3 service of the backup's bucket (Amazon at s3.<region>.amazonaws.com, Wasabi at s3.<region>.wasabisys.com, or the endpoint you set) | the cloud drive's key, to read the bucket's lock settings; nothing is written | when you press **Check the lock** on an off-site backup |
| Remote access | Tailscale (login.tailscale.com) | what Tailscale needs to connect your devices | if you turn it on |
| Family from anywhere | Tailscale's API (api.tailscale.com) | the Tailscale API key you paste, to make a share invite of this NAS, read whether it was accepted, read the key's expiry, or withdraw it | when you save the key, invite or withdraw someone, and while the card or an open invite page checks for acceptance (at most every 5 seconds) |
| Malware scan | ClamAV's signature mirrors (database.clamav.net, through Cloudflare) | nothing about your files: ClamAV only downloads its signatures; files are scanned on the NAS | when you turn on the malware scan, then a few times a day |
| Remote access | the Headscale server you name instead of Tailscale | the same, sent to your own server | if you choose Headscale |
| Remote access | NetBird (api.netbird.io, or the NetBird server you name), and Docker Hub for the netbirdio/netbird image | the setup key you paste and what NetBird needs to connect your devices | if you choose NetBird |
| Anonymous health report | the Kiboto project's receiver (a Cloudflare Worker) | app version, platform, processor type, image variant, a drive-count range, features in use, a random id ([details](HEALTH_SIGNAL.md)) | weekly, only if you turn on **Help improve Kiboto** (off by default) |

Your browser also loads Kiboto itself from the NAS; the desktop does not load fonts,
scripts or images from outside services (app logos come through Kiboto, see above). Links
you click, such as a photo's place on OpenStreetMap, open in a new tab.

`tests/test_sec38_privacy.py` lists every outside address in the code and fails when one is
missing from this page.

## Your controls

- The **Web** switch in the chat, off until you turn it on; your browser remembers it.
- **Help improve Kiboto** (Settings, under Software Updates), off by default; it shows the
  exact report before you turn it on, and turning it off forgets the random id.
- The folders you tick decide what Kib reads. **Forget** deletes what Kib learned from a folder
  and takes it off the list; Kib's regular passes skip it until you tick it again.
- **Delete chats not used for…** sets conversation retention.
- Security Advisor warns if an AI runtime on this NAS is reachable from your network
  without authentication.
