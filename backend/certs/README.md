# Extra certificates

`isrg-root-yr-by-x1.pem`: Let's Encrypt's *ISRG Root YR*, cross-signed by *ISRG Root X1*
(https://letsencrypt.org/certs/gen-y/root-yr-by-x1.pem, SHA-256
`07:26:39:D0:B1:40:D5:BF:FA:E1:6A:D9:C3:F6:CC:60:86:04:06:21:F5:1E:E6:1A:6D:46:A8:91:5C:07:CF:76`).

Unraid's free `*.myunraid.net` certificates are issued by Let's Encrypt YR2, whose chain ends
at Root YR, which isn't in common trust stores yet (October 2026), and Unraid's web server
doesn't send the cross-signed copy. With this file as an extra link, the Unraid API client
verifies the chain up to ISRG Root X1, which is trusted everywhere. It adds no new trust
anchor: the cross-signed certificate is itself signed by X1.
