# The self-hosted runner for hardware budgets (docs/HARDWARE_RUNNER.md).
FROM ghcr.io/actions/actions-runner:2.338.0
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh
USER runner
ENTRYPOINT ["/entrypoint.sh"]
