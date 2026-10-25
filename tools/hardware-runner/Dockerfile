# The self-hosted runner for hardware budgets (docs/HARDWARE_RUNNER.md).
FROM ghcr.io/actions/actions-runner:2.338.0
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/* \
  # a job never needs root: no sudo, no docker group
  && gpasswd -d runner sudo && gpasswd -d runner docker && rm -f /etc/sudoers.d/*
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh
USER runner
ENTRYPOINT ["/entrypoint.sh"]
