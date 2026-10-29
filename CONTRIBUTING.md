# Contributing to ZettNAS Toolkit

Thanks for helping. This page covers the setup, the checks every pull request must pass, and the rules that keep ZettNAS safe on real hardware.

## Setup

```bash
git clone https://github.com/fr0styx/zettnas-toolkit.git && cd zettnas-toolkit

# Run it with your working copy mounted
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d

# Or natively: Python 3.12 and the Node version in .nvmrc
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
npm ci
```

The frontend is plain JavaScript modules bundled by Vite (`npm run dev` for hot reload, `npm run build` into `static/`). It works offline: no CDN links; add libraries with `npm install` so they are bundled.

## Checks

Pull requests run the same checks as CI. Locally:

```bash
# Backend tests in the test container (tests are not shipped in the image)
docker compose -f docker-compose.dev.yml --profile test run --rm zettnas-test

npm run lint          # Ruff lint and format check (Python)
npm test              # frontend tests (Vitest)
npm run lint:js       # ESLint
npm run lint:i18n     # every key in all five languages; hard-coded English may only go down, per file
npm run lint:css      # !important rules, button classes and emoji icons may only go down
npm run build && npm run budget   # first-load size budget
```

Text people read goes through `t('key', 'English')` in scripts and `data-i18n` (or
`data-i18n-title`, `-placeholder`, `-aria-label`) in markup, with the key in all five files under
`frontend/src/locales/`. The translation lint counts the English that doesn't, file by file:
titles, placeholders, labels and the text between tags, ALL-CAPS and text around `${}` included.
`npm run lint:i18n -- --list` prints each one; after translating some, `npm run lint:i18n --
--update-baseline` lowers the numbers in `frontend/scripts/i18n-baseline.json`. A new file starts
at zero.

CI also requires:

- **Coverage**: at least 76% of the backend, and at least 80% of the backend lines your change touches (diff-cover).
- **Types and error handling**: no file may get worse under Pyright, and the number of silent `except: pass` blocks may not grow.
- **Browser tests**: sign-in, the main views and an accessibility (axe) check run in headless Chromium.

## Rules

- **Hardware safety**: never remove or bypass the collector watchdog (`COLLECTOR_WATCHDOG_SECS`), the fan floors, or full fan speed when a hard disk reaches `HDD_CRITICAL_TEMP` (55 °C), an NVMe drive `NVME_CRITICAL_TEMP` (75 °C) or the CPU 80 °C.
- **Sleeping disks**: nothing may wake a disk in standby just to look at it; check standby first (see `backend/services/rag_standby.py`).
- **Paths**: anything that reads, writes or deletes files resolves the path with `backend.fsutil.resolve_within` and stays inside an allowed root.
- **Settings files**: write `data/*.json` with `backend.fsutil.atomic_write_json`, never in place.
- **Errors**: API errors use `backend.errors.error_response(status, detail, code)`; server errors show a reference, never exception text.
- **Frontend**: no monkey-patching of browser functions such as `window.fetch`; use module imports or `ZettEventBus`. Text goes through `t()` with a key in every locale.
- **Docs**: a change to an API, a setting or a hardware interface updates the matching file in `docs/` (`docs/CONFIGURATION.md` is generated from `backend/settings.py`).

## Pull requests

1. Branch from `main` and keep each pull request to one change.
2. Describe what changed for the user and how you tested it; add a line under `## Unreleased` in `CHANGELOG.md` for anything users notice.
3. All checks green before review.

Security problems: report them privately, as described in [SECURITY.md](SECURITY.md).
