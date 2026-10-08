#!/usr/bin/env bash
# ZettNAS Toolkit - Comprehensive CI Pre-Commit / Release Verifier
# Run this script before committing or releasing to ensure 100% GitHub Actions parity.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "=================================================="
echo " [CI Verifier] Step 1: Checking Python & Ruff Lint"
echo "=================================================="
if command -v ruff &> /dev/null; then
    ruff check app.py backend tests
    ruff format --check app.py backend tests
else
    # Execute inside container if available
    ssh -o BatchMode=yes root@10.40.30.249 "docker exec -w /mnt/user/appdata/zettnas-toolkit zettnas-toolkit ruff check app.py backend tests && docker exec -w /mnt/user/appdata/zettnas-toolkit zettnas-toolkit ruff format --check app.py backend tests"
fi
echo "✓ Ruff lint & formatting checks passed!"

echo ""
echo "=================================================="
echo " [CI Verifier] Step 2: Running Pytest Unit & Coverage"
echo "=================================================="
if command -v pytest &> /dev/null; then
    pytest --cov=backend --cov=app --cov-report=xml -v
else
    ssh -o BatchMode=yes root@10.40.30.249 "docker exec -w /mnt/user/appdata/zettnas-toolkit zettnas-toolkit pytest --cov=backend --cov=app --cov-report=xml -v"
fi
echo "✓ Pytest unit & coverage passed!"

echo ""
echo "=================================================="
echo " [CI Verifier] Step 3: Frontend Tests (Vitest Coverage)"
echo "=================================================="
rm -rf coverage/
npm run test:coverage
echo "✓ Frontend Vitest coverage passed!"

echo ""
echo "=================================================="
echo " [CI Verifier] Step 4: Frontend Production Build"
echo "=================================================="
npm run build
echo "✓ Production static assets built successfully!"

echo ""
echo "=================================================="
echo "🎉 ALL CI GITHUB ACTIONS CHECKS PASSED SUCCESSFULLY!"
echo "=================================================="
