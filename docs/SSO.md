# Single sign-on with OpenID Connect

ZettNAS can let people sign in through an OpenID Connect provider such as Authentik,
Keycloak, Authelia, Zitadel, Microsoft Entra ID or Google. Local accounts keep
working alongside it.

## Set up the provider

Create an application (Authentik: *Applications → Providers → OAuth2/OpenID*; Keycloak:
*Clients → Create client*, client authentication on) with:

- **Redirect URI:** shown in ZettNAS under **Security → Single sign-on**, for example
  `https://nas.example.com/api/auth/oidc/callback`. If you reach ZettNAS through a
  reverse proxy, also fill in **Public URL** so the two match.
- **Scopes:** `openid profile email`, plus `groups` (Authentik) or a *groups* mapper
  (Keycloak: *Client scopes → Add mapper → Group Membership*, token claim name
  `groups`, full group path off).
- A confidential client: note the **client ID** and **client secret**.

The issuer URL is the provider's base address for this application:

| Provider | Issuer |
| -------- | ------ |
| Authentik | `https://auth.example.com/application/o/<app-slug>` |
| Keycloak | `https://sso.example.com/realms/<realm>` |
| Authelia | `https://auth.example.com` |

## Set up ZettNAS

Under **Security → Single sign-on**, fill in the issuer, client ID and secret, the
button label and the admin groups, and turn on **Show the single sign-on button**.
The login screen then shows **Sign in with <label>**.

## Accounts and roles

- The first sign-in creates a ZettNAS account named after `preferred_username`. If that
  name is taken by a local account, the new one gets `-sso` appended: a provider login
  never takes over a local account.
- To link existing local accounts instead, turn on `link_by_verified_email` in
  `data/oidc.json`. Then a provider login with a verified email that matches exactly one
  local account signs in as that account.
- Members of an **admin group** become SuperAdmin. `role_map` in `data/oidc.json` maps
  other groups to roles (for example `{"family": "share_user"}`); everyone else gets
  `default_role`. Roles are re-applied at every sign-in unless `sync_roles` is off.
- The provider is responsible for multi-factor authentication for these logins.

## Security notes

- Use HTTPS for the provider. The ID token is checked for issuer, audience, expiry and
  nonce, and the code exchange uses PKCE.
- The client secret is stored in `data/oidc.json` (readable by root only) and never sent
  back to the browser.

## Immich

The one-click Immich app installs the whole stack: the server, machine learning, Valkey
and Postgres on a private network, with a generated database password (kept in
`appdata/immich/.zettnas-secrets.json`). To sign in to Immich with the same provider:

1. At the provider, create a second application for Immich with these redirect URIs:
   `app.immich:///oauth-callback`, `http://<nas-address>:2283/auth/login` and
   `http://<nas-address>:2283/user-settings` (use your HTTPS address if you have one).
2. In Immich, open **Administration → Settings → Authentication → OAuth**, turn it on,
   and enter the same issuer URL, the Immich client ID and secret, and scope
   `openid email profile`. Turn on **Auto register** so family members get an Immich
   account on first sign-in.
3. Set the button text to match ZettNAS (for example "Sign in with Authentik").
