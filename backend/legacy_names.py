"""Names from before the Kiboto rebrand (ZettNAS) that the code still has to know.

Accepted until Kiboto 2.2 (REMOVE_IN), then removed with this file: the ZETTNAS_* environment
variables existing installs set, and the other old names added here as the rename goes on.

Kept for good, elsewhere and on purpose, because data made before depends on them: the data key's
salt (db_crypto._KDF_SALT), the two-factor secret box's key and associated data (secret_box), the
backup manifest name and config-export prefix that restores still read (backup_engine), and the
restic tag on off-site snapshots (offsite_backup). Changing those would make that data unreadable.
"""

import os
from typing import overload

REMOVE_IN = "2.2.0"
ENV_PREFIX = "KIBOTO_"
OLD_ENV_PREFIX = "ZETTNAS_"
OLD_SESSION_COOKIE = "zettnas_session"  # browsers signed in before the rebrand still send it
OLD_NAS_NAME = "zettnas"  # zettnas.local keeps answering beside kiboto.local (D17)
OLD_NAME_CONTAINER = "zettnas-name"  # the name responder's container before the rebrand: replaced


def old_env_name(name: str) -> str | None:
    """ZETTNAS_X for KIBOTO_X; None for any other name."""
    return OLD_ENV_PREFIX + name[len(ENV_PREFIX) :] if name.startswith(ENV_PREFIX) else None


@overload
def getenv(name: str) -> str | None: ...
@overload
def getenv(name: str, default: str) -> str: ...
def getenv(name: str, default: str | None = None) -> str | None:
    """os.environ.get for a KIBOTO_ variable that falls back to its ZETTNAS_ name; the new name wins."""
    if name in os.environ:
        return os.environ[name]
    old = old_env_name(name)
    if old and old in os.environ:
        return os.environ[old]
    return default
