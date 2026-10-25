#!/bin/sh
# Registers once (RUNNER_TOKEN from the repository's "New self-hosted runner" page, valid for an
# hour), then keeps its registration in /home/runner/state so restarts need no token.
set -eu
STATE=/home/runner/state
cd /home/runner
if [ -f "$STATE/.runner" ]; then
  cp "$STATE/.runner" "$STATE/.credentials" "$STATE/.credentials_rsaparams" . 2>/dev/null || true
else
  : "${RUNNER_TOKEN:?first start needs RUNNER_TOKEN}"
  ./config.sh --unattended --url "${RUNNER_URL:-https://github.com/fr0styx/zettnas-toolkit}" \
    --token "$RUNNER_TOKEN" --name "${RUNNER_NAME:-zettnas-hw-1}" --labels zettnas-hardware \
    --no-default-labels --work _work --replace
  mkdir -p "$STATE"
  cp .runner .credentials .credentials_rsaparams "$STATE/"
fi
exec ./run.sh
