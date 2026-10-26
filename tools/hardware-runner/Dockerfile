# The self-hosted runner for hardware budgets and the nightly AI check (docs/HARDWARE_RUNNER.md).
#   docker build -t zettnas-hw-runner --build-context app=. tools/hardware-runner
# The app's Python packages live in /opt/zn-eval (from requirements.lock, so the AI check runs
# the app's own code); /opt/zn-eval/lock.sha256 says which lock they came from.
FROM ghcr.io/actions/actions-runner:2.338.0
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv && rm -rf /var/lib/apt/lists/* \
  # a job never needs root: no sudo, no docker group
  && gpasswd -d runner sudo && gpasswd -d runner docker && rm -f /etc/sudoers.d/*
COPY --from=app requirements.lock /opt/zn-eval/requirements.lock
RUN python3 -m venv /opt/zn-eval \
  && /opt/zn-eval/bin/pip install --no-cache-dir --require-hashes -r /opt/zn-eval/requirements.lock \
  && sha256sum /opt/zn-eval/requirements.lock | cut -d" " -f1 > /opt/zn-eval/lock.sha256
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh
USER runner
ENTRYPOINT ["/entrypoint.sh"]
