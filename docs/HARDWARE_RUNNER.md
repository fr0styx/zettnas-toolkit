# Hardware runner

Some budgets only mean something on a real server: idle CPU, wakeups, memory, what the AI servers
hold when nobody chats (PERF-10). A self-hosted GitHub Actions runner next to a ZettNAS install
measures them every night (`.github/workflows/hardware.yml`, `scripts/hardware_budgets.py`).

## Safety

- The workflow runs only on its schedule or by hand, from `main`. It has no `pull_request`
  trigger, so code from a fork never reaches the machine. No other workflow uses the runner's
  label (`zettnas-hardware`), and the runner has no default labels.
- The runner container sees the host's `/proc` read-only and a results folder. It has no Docker
  socket, no host network, no access to your files, no sudo and no capabilities.
- The repository is public, so its Actions logs are public: the log says only PASS or FAIL per
  budget. The measured numbers are written to the results folder on the machine.

## Setting it up

1. Build the image on the server: `docker build -t zettnas-hw-runner tools/hardware-runner`
2. On GitHub: Settings → Actions → Runners → New self-hosted runner, copy the token.
3. Start it (the token is used once; the registration is kept in the state folder):

```bash
docker run -d --name zettnas-hw-runner --restart unless-stopped --hostname zettnas-hw \
  -e RUNNER_TOKEN=<token> -e HOST_PROC=/host/proc -e HW_RESULTS_DIR=/results \
  -v /proc:/host/proc:ro \
  -v /mnt/user/appdata/zettnas-hw-runner/state:/home/runner/state \
  -v /mnt/user/appdata/zettnas-hw-runner/results:/results \
  --memory 1g --cap-drop ALL --security-opt no-new-privileges zettnas-hw-runner
```

Results: one JSON file per run in the results folder. Budgets can be tuned with
`HW_BUDGET_IDLE_CPU`, `HW_BUDGET_WAKEUPS`, `HW_BUDGET_BACKEND_MEMORY`, `HW_BUDGET_AI_MEMORY`.
