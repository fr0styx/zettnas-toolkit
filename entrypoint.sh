#!/bin/sh
set -e

if ! command -v smartctl >/dev/null 2>&1; then
  apt-get update && apt-get install -y --no-install-recommends smartmontools udev
  rm -rf /var/lib/apt/lists/*
fi

pip install --no-cache-dir -r requirements.txt
playwright install --with-deps chromium

exec python3 app.py
