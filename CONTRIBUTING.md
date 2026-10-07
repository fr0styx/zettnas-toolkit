# Contributing to ZettNAS Toolkit

Thank you for your interest in improving ZettNAS Toolkit! This guide will help you set up your development environment, run tests, and adhere to project standards.

---

## 1. Development Setup

### Option A: Local Container Development (Recommended)

Run the local development container with live bind-mounts:

```bash
# Clone the repository
git clone https://github.com/fr0styx/zettnas-toolkit.git
cd zettnas-toolkit

# Start with local development bind mounts
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d

# Check live logs
docker compose logs -f zettnas-toolkit
```

### Option B: Native Host Development

```bash
# Python 3.12 virtual environment
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install ruff pytest pytest-cov httpx
playwright install chromium

# Frontend setup
npm install
npm test
npm run build
```

---

## 2. Frontend Development

The frontend is written in vanilla ES modules and bundled using Vite. It is strictly **offline-first**; external CDN dependencies (e.g. unpkg, jsdelivr) are prohibited.

```bash
# Start Vite development server with HMR
npm run dev

# Compile production bundle into static/
npm run build
```

When adding third-party frontend libraries, install them via `npm install` and import them directly so they are compiled into the local distribution bundle.

---

## 3. Code Quality & Testing

All contributions must pass the automated test suite and Ruff linter.

### Running the Test Suite
```bash
# Run Python backend test suite with test coverage
pytest --cov=backend --cov=app -v

# Run Frontend unit test suite (Vitest + JSDOM)
npm test
```

### Linting & Formatting
```bash
# Check code style
ruff check app.py backend tests

# Check formatting
ruff format --check app.py backend tests

# Auto-format
ruff format app.py backend tests
```

---

## 4. Architecture & Security Guidelines

- **Hardware Safety**: Never remove or bypass the `COLLECTOR_WATCHDOG_SECS` failsafe, thermal floor clamps, or the 100% duty cycle override at >= 55 °C.
- **Filesystem Security**: Any endpoint performing file browsing, directory creation, or file deletion MUST sanitize paths using `backend.fsutil` and verify that the target path is strictly contained within an allow-listed root.
- **State Integrity**: All state modifications to `data/*.json` MUST use `backend.fsutil.atomic_write_json` to avoid file corruption during container halts.
- **API Consistency**: All API errors must be returned using `backend.errors.error_response(status, detail, code)`.
- **Frontend Isolation**: Do not monkey-patch browser primitives (e.g. `window.fetch`) or pollute the global `window` object. Use ES module imports or `ZettEventBus`.

---

## 5. Pull Request Process

1. Fork the repository and create your branch from `main`: `git checkout -b feature/my-cool-feature`.
2. Make your changes with clear, descriptive commit messages.
3. Ensure all 195+ backend tests and frontend Vitest tests pass and Ruff reports 0 warnings.
4. If modifying hardware interfaces or API endpoints, update the corresponding documentation in `docs/`.
5. Open a Pull Request detailing the problem solved and testing steps performed.
