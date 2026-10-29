# Translating ZettNAS

ZettNAS speaks English, German, Spanish, French and Chinese. Every text people read has a key in
all five files under `frontend/src/locales/`, and `npm run lint:i18n` checks them.

## How to write

- **Plain words for a household, not a data centre.** "Back up my phone", not "Mobile ingest
  pipeline". Product names (Immich, Tailscale, Docker) stay as they are.
- **One form of address per language**, checked by the lint:

  | Language | Address | Example |
  |---|---|---|
  | German | Sie | „Melden Sie sich an.“ |
  | Spanish | tú | "Inicia sesión." |
  | French | vous | « Connectez-vous. » |
  | Chinese | 你 (not 您) | "请登录。" |

- **Sentence case** for titles, buttons and labels ("Add a person", not "ADD A PERSON"). Capitals
  for emphasis come from CSS, never from the string.
- **No emoji in strings.** An icon belongs in the markup, with `aria-hidden="true"`, so it isn't
  read aloud and translators don't have to carry it. The lint counts the strings that still have
  one; the number can only go down.
- **Keep the placeholders** (`{name}`, `{count}`) exactly; the lint fails when one is dropped or
  invented.

## Counts

A count gets a plural rule, so "1 files" never shows:

```
"fm.copied": "Copied {count, plural, one {# item} other {# items}}"
"fm.copied": "{count, plural, one {# Element} other {# Elemente}} kopiert"
```

`#` is the number. Chinese has no plural forms and keeps one form: `"已复制 {count} 项"`. The lint
fails when a new English string counts something without a plural rule.

## Numbers, dates and times

Use `formatNumber`, `formatBytes`, `formatPercent` and `formatDateTime` from
`frontend/src/format.js`: they follow the person's language (1,5 GB in German, 1.5 GB in
English). `toFixed()` and `toLocale*String()` outside `format.js` are counted or refused by the
lint.

## Checks

```bash
npm run lint:i18n                      # keys, placeholders, address, counts
npm run lint:i18n -- --list            # each hard-coded English string, per file
npm run lint:i18n -- --update-baseline # after translating: lower the numbers
```

The German, Spanish, French and Chinese texts were written with care but not yet reviewed by
native speakers; corrections are welcome.
