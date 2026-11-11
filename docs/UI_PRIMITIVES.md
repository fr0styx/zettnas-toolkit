# UI primitives and colour tokens

New markup uses these instead of inline styles. Two tests keep it that way: the light-theme
test (no new hard-coded colours) and the UI ratchets (no file gains inline styles or
unstyled buttons).

## Primitives

`frontend/src/ui/primitives.js` builds them as HTML strings; text arguments are escaped.

| Primitive  | Class                                   | Builder                                              |
|------------|-----------------------------------------|------------------------------------------------------|
| Button     | `.btn-pill-toggle`                      | `uiButton({ label, variant, small, block, iconName })` |
| Field      | `.kb-field` (label above its control)   | `uiField({ label, control, hint, id })`              |
| Card       | `.kb-card`, `--boxed`, `--divided`      | `uiCard({ title, body, variant })`                   |
| PaneHeader | `.mgmt-card-intro` (icon, title, line)  | `uiPaneHeader({ title, desc, iconName })`            |

Button variants: `is-primary` (the one main action), `is-danger` (deletes and other
destructive actions), `is-ghost` (quiet, e.g. tabs and toolbar actions), plus `is-small` and
`is-block`. With no variant it is the secondary button.

### Lists, tags and states

For a list of things with columns (people, backup jobs, snapshots), in `50-components.css`:

| Class | What it is |
|---|---|
| `.kb-datatable-wrap` | the scrolling, rounded box around a list |
| `.kb-datatable` | the table: an uppercase header row, 10 px cells, a line between rows; `--compact` (8 px) and `--roomy` (12 px, the row's own text size) |
| `.is-end`, `.is-strong`, `.is-bold`, `.is-muted`, `.is-soft`, `.is-dim`, `.is-mono` | on a cell: right-aligned, emphasised, quiet or monospaced |
| `.kb-datatable-msg` (`.is-crit`) | the one-row "loading" or "couldn't load" message |
| `.kb-sub` (`.is-spaced`) | the small grey line under a name |
| `.kb-actions` | the buttons at the end of a row |
| `.kb-tag` + `--info`, `--ok`, `--warn`, `--crit`, `--plain` | a small coloured label |
| `.kb-state--ok`, `--crit`, `--idle`, `--busy` | the result of the last run, in words |
| `.kb-load-error` | a list that couldn't be loaded |

(`.kb-table` is the older, denser table of the AI access and protection cards.)

## Colour tokens

Defined in `frontend/src/styles/50-components.css`; their light-theme values are generated
into `58-light-palette.css` by `scripts/light_theme.py`.

| Role        | Tokens                                                                                  |
|-------------|-----------------------------------------------------------------------------------------|
| Text        | `--kb-text-strong`, `-bright`, `--kb-text`, `-soft`, `-muted`                           |
| Status text | `--kb-text-accent`, `-ok`, `-warn`, `-crit`, `-ai`                                      |
| Lines       | `--kb-line-5` … `--kb-line-20` (a white line at that opacity, in percent)               |
| Glazes      | `--kb-glaze-2` … `--kb-glaze-15` (a white layer over a surface)                         |
| Shades      | `--kb-shade-20` … `--kb-shade-40` (a black layer over a surface)                        |

`python scripts/light_theme.py convert` turns a new hard-coded colour into its token when
there is one, and into a light-theme wrapper otherwise.

## Ratchets

`python scripts/ui_ratchets.py` reports files with more inline styles or unstyled buttons
than `tests/ui_ratchets.json` records; `--update` records the lower counts after a clean-up.
`python scripts/ui_buttons.py --write` moves buttons styled inline onto `.btn-pill-toggle`.

`npm run lint:css` holds `!important` per file (a new file starts at zero) and the number of
places that build markup with the primitives above, which may only go up (UX-32).
