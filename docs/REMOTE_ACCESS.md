# Use from anywhere

Open ZettNAS, and back up your phone's photos to Immich, away from home without opening a
port on your router. ZettNAS joins a private network of your devices (a *tailnet*) and gives
itself an address there that only your devices can reach.

Find it under **Network → Tailscale & WireGuard → Use from anywhere**.

## Tailscale (a free account)

1. Choose **Tailscale** and press **Connect**. ZettNAS sets up the official Tailscale container
   if it isn't there yet.
2. Scan the code with your phone, or open the link, and sign in with Google, Apple, Microsoft
   or GitHub. The card updates by itself.
3. Install the Tailscale app on your phone and sign in with the same account.
4. Press **Turn on HTTPS**. ZettNAS then has an address like `https://zettnas.tail1234.ts.net/`
   and Immich `https://zettnas.tail1234.ts.net:8443/`. Scan the code on the card to open
   ZettNAS on the phone, and type the Immich address in the Immich app.

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
`headscale nodes register`. ZettNAS repeats the server's address every time Tailscale
signs in again, so the node never moves back to Tailscale's servers.

Headscale gives no HTTPS certificates, so the addresses start with `http://` and use the
node's tailnet name or its 100.x address. The traffic is still encrypted end to end by
WireGuard.

## What it does and doesn't do

- Nothing is opened on your router, and nobody outside your tailnet can reach the addresses.
  Funnel (making ZettNAS public on the internet) stays off unless you turn it on in the
  Tailscale details below the card.
- **Disconnect** stops serving and leaves the tailnet; the node stays signed in, so
  **Connect** brings it back without a new sign-in.
- The settings live in `remote_access.json` in the data folder.

Behind the scenes: `tailscale up` (with `--login-server` for Headscale), then
`tailscale serve --bg --https=443 http://127.0.0.1:<ZettNAS port>` and
`--https=8443` for Immich.
