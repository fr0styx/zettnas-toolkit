# UI primitives and colour tokens

New markup uses these instead of inline styles. Two tests keep it that way: the light-theme
test (no new hard-coded colours) and the UI ratchets (no file gains inline styles or
unstyled buttons).

## Primitives

`frontend/src/ui/primitives.js` builds them as HTML strings; text arguments are escaped.

| Primitive  | Class                                   | Builder                                              |
|------------|-----------------------------------------|------------------------------------------------------|
| Button     | `.btn-pill-toggle`                      | `uiButton({ label, variant, small, block, iconName })` |
| Field      | `.zn-field` (label above its control)   | `uiField({ label, control, hint, id })`              |
| Card       | `.zn-card`, `--boxed`, `--divided`      | `uiCard({ title, body, variant })`                   |
| PaneHeader | `.mgmt-card-intro` (icon, title, line)  | `uiPaneHeader({ title, desc, iconName })`            |

Button variants: `is-primary` (the one main action), `is-danger` (deletes and other
destructive actions), `is-ghost` (quiet, e.g. tabs and toolbar actions), plus `is-small` and
`is-block`. With no variant it is the secondary button.

## Colour tokens

Defined in `frontend/src/styles/50-components.css`; their light-theme values are generated
into `58-light-palette.css` by `scripts/light_theme.py`.

| Role        | Tokens                                                                                  |
|-------------|-----------------------------------------------------------------------------------------|
| Text        | `--zn-text-strong`, `-bright`, `--zn-text`, `-soft`, `-muted`                           |
| Status text | `--zn-text-accent`, `-ok`, `-warn`, `-crit`, `-ai`                                      |
| Lines       | `--zn-line-5` … `--zn-line-20` (a white line at that opacity, in percent)               |
| Glazes      | `--zn-glaze-2` … `--zn-glaze-15` (a white layer over a surface)                         |
| Shades      | `--zn-shade-20` … `--zn-shade-40` (a black layer over a surface)                        |

`python scripts/light_theme.py convert` turns a new hard-coded colour into its token when
there is one, and into a light-theme wrapper otherwise.

## Ratchets

`python scripts/ui_ratchets.py` reports files with more inline styles or unstyled buttons
than `tests/ui_ratchets.json` records; `--update` records the lower counts after a clean-up.
`python scripts/ui_buttons.py --write` moves buttons styled inline onto `.btn-pill-toggle`.
