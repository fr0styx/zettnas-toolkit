# Privacy and data flow

ZettNAS runs on your hardware. This page lists everything it sends off the NAS, and when.
If something here is wrong, please open an issue.

## Stays on the NAS

- Your files, the search index (`rag_index.db`) and AI conversations.
- Questions you ask Ask Zetty and the answers, when the chat model runs on this NAS
  (Ollama or OpenVINO Model Server). ZettNAS only talks to AI runtimes on this machine or
  its Docker network, or to the address you set in **AI settings**; it never tries your
  router or other LAN hosts.
- Photos sent for captions and text reading. They go to the vision model on this NAS,
  at most 896 pixels on the long side, and nowhere else.
- Hardware readings, logs and settings, and the file activity log (who changed which file,
  kept 90 days).

ZettNAS has no analytics and does not phone home. The one exception is the anonymous weekly
health report below, which is off unless you turn it on.

## Leaves the NAS only when you use the feature

| Feature | Goes to | What is sent | When |
|---|---|---|---|
| Ask Zetty web search | DuckDuckGo (duckduckgo.com, html.duckduckgo.com, api.duckduckgo.com), Wikipedia (en.wikipedia.org), and the pages found | your question (or search words from it) | only in chats where you turned on **Web**; the answer lists the services used |
| Ask Zetty weather | wttr.in | the place name | same as above |
| Desktop weather widget | api.open-meteo.com and geocoding-api.open-meteo.com (from your browser) | city name, then its coordinates | while the widget is on the desktop |
| Calendar holidays | date.nager.at (from your browser) | year and country code | when the calendar shows public holidays |
| Update check | api.github.com, ghcr.io | your IP address and the version request | when you open **Updates** |
| Container image updates | the registries your containers come from (e.g. Docker Hub at index.docker.io, ghcr.io) | image names | when you check for or apply container updates |
| App catalog | github.com / raw.githubusercontent.com and the catalog sources you add | template requests | when you open or refresh the catalog |
| App logos in the catalog | cdn.jsdelivr.net (the dashboard-icons set) or raw.githubusercontent.com, asked by ZettNAS, never by your browser | the logo's address | once per logo; ZettNAS keeps a copy, and logos from any other host aren't shown |
| Model search and install | huggingface.co, the Ollama registry | model names you search for or install | when you search for or install a model |
| VM installer images | the OS vendor download servers: releases.ubuntu.com, cdimage.debian.org, download.fedoraproject.org, fedorapeople.org (Windows drivers), dl-cdn.alpinelinux.org, download.sys.truenas.net, software-download.microsoft.com | the download request | when you download an ISO from the VM catalog |
| Notifications | the services you set up (ntfy.sh, Slack, Discord, email, Telegram), or an address on your own network such as Home Assistant or Gotify (never this NAS itself or a cloud metadata address) | the alert text | when an alert fires |
| Phone notifications (Web Push) | the push service of the phone's browser maker (Google, Mozilla, Apple or Microsoft) | the alert, encrypted for that phone: the push service sees only ciphertext and when it was sent | when an alert fires, to phones where you turned notifications on |
| Cloud remotes and backups | the providers you connect (S3, B2, OneDrive, Google Drive, …) | the files you choose to sync | as you configure |
| Remote access | Tailscale (login.tailscale.com) | what Tailscale needs to connect your devices | if you turn it on |
| Remote access | the Headscale server you name instead of Tailscale | the same, sent to your own server | if you choose Headscale |
| Anonymous health report | the ZettNAS project's receiver (a Cloudflare Worker) | app version, platform, processor type, image variant, a drive-count range, features in use, a random id ([details](HEALTH_SIGNAL.md)) | weekly, only if you turn on **Help improve ZettNAS** (off by default) |

Your browser also loads ZettNAS itself from the NAS; the desktop does not load fonts,
scripts or images from outside services (app logos come through ZettNAS, see above). Links
you click, such as a photo's place on OpenStreetMap, open in a new tab.

`tests/test_sec38_privacy.py` lists every outside address in the code and fails when one is
missing from this page.

## Your controls

- The **Web** toggle in each chat, off by default.
- **Help improve ZettNAS** (Settings, under Software Updates), off by default; it shows the
  exact report before you turn it on, and turning it off forgets the random id.
- **Watched** and **Excluded** folders decide what the index may read; **Forget** removes a
  folder from it.
- **Delete chats not used for…** sets conversation retention.
- Security Advisor warns if an AI runtime on this NAS is reachable from your network
  without authentication.
