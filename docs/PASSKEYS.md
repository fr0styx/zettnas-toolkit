# Passkeys

A passkey signs you in with your phone, your laptop's fingerprint reader or face unlock, or a security
key. There is no password to type and nothing a fake page could steal: the passkey only answers the
Kiboto address it was made on.

## Add one

Users → Two-step sign-in → **Passkeys** → **Add a passkey**, then follow your browser. Give it a name
you will recognise ("Anna's phone"). Add a second one (another device or a security key) so losing
one device doesn't lock you out.

## Sign in

- On the sign-in page, **Sign in with a passkey**: no name or password needed.
- Or sign in with your password as usual: when you have a passkey, Kiboto asks for it as the second
  step (**Use a passkey**). If you also set up the code app, either works.

A passkey counts as two-step sign-in, so it meets a role's "Require two-step sign-in" rule. Your last
passkey can't be removed while the role requires two-step sign-in and no code app is set up.

## Where passkeys work

Browsers offer passkeys only on a secure page with a name: `https://<name>` (for example Kiboto's
Tailscale address, or a reverse proxy with a certificate) or `http://localhost`. They don't work at
`http://192.168.x.x:8082`. A passkey belongs to the address it was made on; open Kiboto at the same
address to use it. The card says when the current address can't use passkeys.

## If you lose every device

An administrator can remove all of your passkeys (`DELETE /api/users/<id>/passkeys`, recorded in the
security log); then sign in with your password and add new ones. Recovery codes belong to the code
app; a passkey-only account has none.

Behind the scenes: WebAuthn with Yubico's `fido2` library. The device's PIN or fingerprint is
required (user verification), challenges are kept on the server for five minutes and used once, and
the browser's origin must match the address.
