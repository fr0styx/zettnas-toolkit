# Hardware runner

Some checks only mean something on a real server. A self-hosted GitHub Actions runner next to a
ZettNAS install runs three every night (`.github/workflows/hardware.yml`), in this order:

1. **Budgets** (PERF-10, `scripts/hardware_budgets.py`): idle CPU, wakeups and processes started,
   for the whole app container (every process in its cgroup, sampled each second), the backend's
   memory and what the AI servers hold when nobody chats, over a 5-minute soak. Connections from
   the machine itself (the healthcheck) don't count as someone using the app. Pull requests get
   a shorter version in CI: one idle minute of a freshly started backend, where starting more
   than 10 processes a minute fails the run.
2. **Spin-down** (PERF-2, `scripts/hardware_spindown.py`): for 30 minutes, whether a spinning disk
   that has been idle long enough to sleep sees I/O while the ZettNAS backend does storage I/O.
   It only reads kernel counters (`/proc/diskstats`, `/sys/block/*/queue/rotational`, the
   backend's `/proc/<pid>/io`); it never sends a command to a drive, so it can't wake one or put
   one to sleep. "No I/O" stands in for "asleep", since the spin state can't be read without
   asking the drive.
3. **AI eval** (AI-16, `scripts/hardware_ai_eval.py`): the search and answer eval
   (`tests/rag_eval`, all sets and the documents set) against the embedder and chat server this
   install uses, compared with this machine's own last result. It only sends questions; it never
   installs, pulls or changes a model.

## Safety

- The workflow runs only on its schedule or by hand, from `main`. It has no `pull_request`
  trigger, so code from a fork never reaches the machine. No other workflow uses the runner's
  label (`zettnas-hardware`), and the runner has no default labels.
- The runner joins the app's private Docker network (`zettnas-toolkit_default`) so the AI eval
  can reach the model servers, which have no published ports and no sign-in; that is also why
  only code from `main` may run there.
- The runner container sees the host's `/proc` read-only and a results folder. It has no Docker
  socket, no host network, no access to your files, no sudo and no capabilities.
- The repository is public, so its Actions logs are public: the log says only PASS or FAIL per
  budget. The measured numbers are written to the results folder on the machine.

## Setting it up

1. Build the image on the server, from the repository root (the app's Python packages for the AI
   eval are installed from `requirements.lock`):
   `docker build -t zettnas-hw-runner --build-context app=. tools/hardware-runner`
2. On GitHub: Settings → Actions → Runners → New self-hosted runner, copy the token.
3. Start it (the token is used once; the registration is kept in the state folder):

```bash
docker run -d --name zettnas-hw-runner --restart unless-stopped --hostname zettnas-hw \
  -e RUNNER_TOKEN=<token> -e HOST_PROC=/host/proc -e HW_RESULTS_DIR=/results \
  -v /proc:/host/proc:ro \
  -v /mnt/user/appdata/zettnas-hw-runner/state:/home/runner/state \
  -v /mnt/user/appdata/zettnas-hw-runner/results:/results \
  --memory 1g --cap-drop ALL --security-opt no-new-privileges \
  --network zettnas-toolkit_default zettnas-hw-runner
```

When `requirements.lock` changes, rebuild the image and re-create the container the same way
(the state folder keeps the registration, so no new token is needed). Until then the AI eval
reports SKIP: it runs the app's own code and needs the packages that code was locked with.

Results: one JSON file per budget run in the results folder, `spindown/` and `ai/` for the other
checks. The AI eval keeps its baselines there too (`ai/baseline_<set>.json`); the first run, or a
run with another embedding or chat model, records a new one. Budgets can be tuned with
`HW_BUDGET_IDLE_CPU`, `HW_BUDGET_WAKEUPS`, `HW_BUDGET_BACKEND_MEMORY`, `HW_BUDGET_AI_MEMORY`.
