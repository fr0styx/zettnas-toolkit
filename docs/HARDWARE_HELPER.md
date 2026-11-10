# The hardware helper

On Zettlab boxes Kiboto sets the fans and reads the front COPY button through two hardware registers it
reaches by opening `/dev/mem`. That access (the `SYS_RAWIO` capability and the `/dev/mem` device rule)
can read and change any of the computer's memory, so it shouldn't sit in a web app.

**Hardware → Fans → Hardware helper** moves it into `kiboto-hw`, a small container made from Kiboto's
own image that:

- has no network, a read-only file system and every capability dropped except `SYS_RAWIO`;
- maps only the two pages Kiboto needs (the fan controller and the button's GPIO block);
- answers four requests on a socket in Kiboto's data folder (`hw/hw.sock`): read the fans, set one
  fan's PWM (0–183), read the button, and a ping. Anything else is refused.

Turning it on is confirmed (it is a container with raw hardware access). From then on the fans and the
button go through the helper. At the **next update**, Kiboto's own container is recreated without
`SYS_RAWIO` and without the `/dev/mem` rule, while the helper answers; the choice is recorded in
`hw_helper.json`. Turning the helper off later keeps it running until the following update gives Kiboto
its access back, so the fans are never left without a way to be set.

On Unraid, the template's Extra Parameters still list `--cap-add=SYS_RAWIO` and `c 1:1 rwm`; editing
the container in Unraid's own page brings them back. The fan watchdog sidecar keeps its own access.
