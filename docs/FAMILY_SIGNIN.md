# One sign-in for the family's apps

Users → **One sign-in for the family's apps** gives everyone one way to sign in to the apps on the NAS:
a passkey on their phone, through [Pocket ID](https://pocket-id.org), which Kiboto runs and keeps filled.

## Turning it on

It needs HTTPS in your tailnet first (Network → Use from anywhere → Turn on HTTPS): passkeys only work on
https addresses. Then **Turn on family sign-in** (confirmed):

- Kiboto starts Pocket ID in a container of its own, `kiboto-id` (the distroless image, which runs as a
  normal user with every capability dropped), on port 1411, keeping its data in Kiboto's data folder
  under `pocket-id`.
- Its encryption key and the API key Kiboto uses to talk to it are made once and kept sealed.
- Pocket ID's address is `https://<this NAS>.<tailnet>.ts.net:11411`, served by remote access like
  every other app.
- Each active Kiboto user gets a Pocket ID account in the group `kiboto-family`; administrators stay
  administrators. Sign-ups from outside are off.

Turning it off stops and removes the container. Its data stays, so turning it on again keeps every
passkey.

## People

Kiboto keeps Pocket ID's people in step with its own when it is turned on and whenever you press
**Update people now**: new users are added, changed names and e-mail addresses follow, and a user
turned off or removed in Kiboto is turned off in Pocket ID.

Pocket ID has no passwords. **Send a sign-in link** copies a link that signs that person in once
(it works for 24 hours); there they add a passkey on their phone or computer.

## Connecting an app

Kiboto has presets for Immich, Nextcloud, Paperless-ngx, Audiobookshelf and Jellyfin. For an app
running here with its HTTPS address, **Connect** (confirmed) makes it a client in Pocket ID that only
the family group may use, with the callback addresses that app expects. It then shows the issuer URL,
the client ID and the client secret, and where they go in that app's settings. The secret is shown
only then and Kiboto doesn't keep it; **New secret** makes a new client if it is lost.
**Disconnect** removes the client from Pocket ID; the app's own sign-in settings stay until you
change them there.
