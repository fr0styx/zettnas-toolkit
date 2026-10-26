"""
ZettNAS Toolkit Backend Package
Modularized architecture for chassis management, telemetry, and LCD dashboard.
"""

__version__ = "1.10.3"

# logger.debug("<where>: ignored error", exc_info=True) is counted, warned about and shown in
# diagnostics instead of vanishing at debug level (ARC-4)
from backend.ignored_errors import install as _install_ignored_errors  # noqa: E402

_install_ignored_errors()
