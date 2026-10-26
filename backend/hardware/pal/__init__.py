"""The storage platform abstraction layer (PAL), one module per host platform.

backend.hardware.pal_storage is the facade that re-exports it and picks the adapter
(get_storage_platform). Split out of a single 4,000-line module (ARC-5)."""
