"""
ZettNAS Toolkit - Root Application Entrypoint Shim
Delegates to backend.main for modular backend architecture.
"""

from backend.main import (  # noqa: F401
    ZettServer,
    _shutdown_fans,
    app,
    fan_watchdog_daemon,
    lifespan,
    main,
    startup_system,
)

if __name__ == "__main__":
    main()
