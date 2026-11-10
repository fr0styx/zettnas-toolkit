# Use from anywhere

Open Kiboto, and back up your phone's photos to Immich, away from home without opening a
port on your router. Kiboto joins a private network of your devices (a *tailnet*) and gives
itself an address there that only your devices can reach.

Find it under **Network → Tailscale & WireGuard → Use from anywhere**.

## Tailscale (a free account)

1. Choose **Tailscale** and press **Connect**. Kiboto sets up the official Tailscale container
   if it isn't there yet.
2. Scan the code with your phone, or open the link, and sign in with Google, Apple, Microsoft
   or GitHub. The card updates by itself.
3. Install the Tailscale app on your phone and sign in with the same account.
4. Press **Turn on HTTPS**. Kiboto then has an address like `https://kiboto.tail1234.ts.net/`
   and Immich `https://kiboto.tail1234.ts.net:8443/`. Scan the code on the card to open
   Kiboto on the phone, and type the Immich address in the Immich app.

HTTPS needs **MagicDNS** and **HTTPS certificates** turned on, on the DNS page of the
Tailscale admin console. If Tailscale asks to allow it for this machine, the page opens
when you press the button; allow it and press the button again.

## Headscale (no account anywhere)

[Headscale](https://headscale.net) is an open-source control server you run yourself, for
example on a small VPS. Choose **My own Headscale server**, give its address
(`https://headscale.example.com`) and, if you made one, a pre-auth key:

```bash
headscale preauthkeys create --user <you>
```

Without a key, the card shows the server's sign-in link; approve it on the server with
`headscale nodes register`. Kiboto repeats the server's address every time Tailscale
signs in again, so the node never moves back to Tailscale's servers.

Headscale gives no HTTPS certificates, so the addresses start with `http://` and use the
node's tailnet name or its 100.x address. The traffic is still encrypted end to end by
WireGuard.

## Share links and chosen apps from anywhere

Two cards in Network → File Sharing Services put things on the public internet through Tailscale
Funnel, each confirmed first. Nothing changes on your router, and it works behind a provider's
shared address (CGNAT).

- **Share links from anywhere** publishes only the share links, on port 8443.
- **Apps from anywhere** puts one app you choose on a port of its own: 10000, or 443 when remote
  access doesn't serve Kiboto there. Anyone with the address reaches the app's own sign-in page, so
  pick apps that have one. Kiboto's own page is never offered. Apps that control the server (Docker
  managers, log viewers, web terminals) are marked and come with a warning. Publishing and taking an
  app off are written to the security log.

Funnel traffic goes through Tailscale's relays, so big transfers are slower than at home.

**Before Funnel works**, the tailnet's owner turns on two things in Tailscale, once: HTTPS certificates
(admin console → DNS → Enable HTTPS) and Funnel for this device (an approval page). Kiboto can't switch
these on itself; it reads them from Tailscale's status and shows both cards a checklist with a link
for each, which ticks itself within seconds of each click. Pressing a card's button before that is
fine: Kiboto keeps the request for an hour and finishes it as soon as both are done. With your own
Headscale server there is no Funnel.

## Family from anywhere: each person their own way in

Network → File Sharing Services → **Family from anywhere** lets each Kiboto user reach this NAS from
outside with their own free Tailscale account. They see only the NAS, nothing else on your tailnet, and
they still sign in to Kiboto with their own name and password.

1. Once: open Tailscale's [Keys page](https://login.tailscale.com/admin/settings/keys), make an
   **API access key** and paste it into the card. Tailscale lets only a person's own key make share
   invites, and such a key lasts at most 90 days; Kiboto keeps it sealed, shows how long it has left and
   warns two weeks before it runs out. Invites already accepted keep working after it expires.
2. Click **Invite** next to a person and confirm. Send them the message (**Copy message**) or let them
   scan the **QR code**. The invite works once and for 7 days.
3. Their page knows their phone or computer and shows three steps: get the Tailscale app, sign in with
   Google, Apple or Microsoft (or a Tailscale account), accept. It notices when they are in and then
   offers **Open Kiboto**; adding it to the home screen keeps it one tap away.

The page lives under the share-link address, so it opens from anywhere when **Share links from
anywhere** is on. Without it, the message carries Tailscale's own invite link and the steps instead.

The card shows who is invited, who joined and who is online. **Withdraw** cancels an open invite.
Tailscale has no way to take back an accepted share through its API: **Remove access** takes the
person off the card and opens Tailscale's Machines page, where you remove them under this NAS →
Sharing. With your own Headscale server there are no share invites; give each person a key from it.

## What it does and doesn't do

- Nothing is opened on your router, and nobody outside your tailnet can reach the addresses.
  Funnel (making Kiboto public on the internet) stays off unless you turn it on in the
  Tailscale details below the card.
- **Disconnect** stops serving and leaves the tailnet; the node stays signed in, so
  **Connect** brings it back without a new sign-in.
- The settings live in `remote_access.json` in the data folder.

Behind the scenes: `tailscale up` (with `--login-server` for Headscale), then
`tailscale serve --bg --https=443 http://127.0.0.1:<Kiboto port>` and
`--https=8443` for Immich.
