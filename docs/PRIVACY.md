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
- Hardware readings, logs and settings.

ZettNAS has no analytics or telemetry and does not phone home.

## Leaves the NAS only when you use the feature

| Feature | Goes to | What is sent | When |
|---|---|---|---|
| Ask Zetty web search | DuckDuckGo, Wikipedia, and the pages found | your question (or search words from it) | only in chats where you turned on **Web**; the answer lists the services used |
| Ask Zetty weather | wttr.in | the place name | same as above |
| Desktop weather widget | open-meteo.com (from your browser) | city name, then its coordinates | while the widget is on the desktop |
| Calendar holidays | date.nager.at (from your browser) | year and country code | when the calendar shows public holidays |
| Update check | api.github.com, ghcr.io | your IP address and the version request | when you open **Updates** |
| Container image updates | the registries your containers come from (e.g. Docker Hub, ghcr.io) | image names | when you check for or apply container updates |
| App catalog | github.com / raw.githubusercontent.com and the catalog sources you add | template requests | when you open or refresh the catalog |
| Model search and install | huggingface.co, the Ollama registry | model names you search for or install | when you search for or install a model |
| VM installer images | the OS vendor download servers (Ubuntu, Debian, Fedora, Alpine, TrueNAS, Microsoft) | the download request | when you download an ISO from the VM catalog |
| Notifications | the services you set up (ntfy, Slack, Discord, email, Telegram) | the alert text | when an alert fires |
| Cloud remotes and backups | the providers you connect (S3, B2, OneDrive, Google Drive, …) | the files you choose to sync | as you configure |
| Remote access | Tailscale | what Tailscale needs to connect your devices | if you turn it on |

Your browser also loads ZettNAS itself from the NAS; the desktop does not load fonts,
scripts or images from outside services.

## Your controls

- The **Web** toggle in each chat, off by default.
- **Watched** and **Excluded** folders decide what the index may read; **Forget** removes a
  folder from it.
- **Delete chats not used for…** sets conversation retention.
- Security Advisor warns if an AI runtime on this NAS is reachable from your network
  without authentication.
