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
OLD_IMAGE_REPO = "fr0styx/zettnas-toolkit"  # CI also publishes and signs every image under this name
OLD_GITHUB_REPO = "fr0styx/zettnas-toolkit"  # images signed before the repo's rename carry this identity
OLD_MANAGED_LABEL = "com.zettnas.managed"  # new containers carry both (an older version, after a
OLD_APP_LABEL = "com.zettnas.app"  # rollback, knows only these)
OLD_APP_NETWORK_PREFIX = "zettnas-app-"  # an app's network made before keeps its name
OLD_FOLLOW_TAG_LABEL = "zettnas.image.follow-tag"
OLD_AI_PACK = "zettnas-ai"  # an AI pack made before keeps its container, models folder and model names
OLD_AI_PACK_LABEL = "zettnas.ai-pack"
OLD_AI_PACK_MODELS = ("zettnas-chat", "zettnas-embed")
OLD_AI_APP_MODELS = ("zettnas-chat", "zettnas-embed")  # "AI for apps" still answers to these ids
OLD_SAMBA = "zettnas-samba"  # sidecars made before are found (Samba) or replaced (SFTP, the updater)
OLD_SFTP = "zettnas-sftp"
OLD_SELF_UPDATER = "zettnas-self-updater"
OLD_APP_CONTAINER = "zettnas-toolkit"  # the app's own container on installs made before
OLD_MODEL_SERVERS = ("zettnas-ollama", "zettnas-ovms")
OLD_SESSION_COOKIE = "zettnas_session"  # browsers signed in before the rebrand still send it
OLD_CANARY_NAME = "!ZettNAS-guard-file.docx"  # the ransomware guard's file before the rebrand
OLD_NAS_NAME = "zettnas"  # zettnas.local keeps answering beside kiboto.local (D17)
OLD_NAME_CONTAINER = "zettnas-name"  # the name responder's container before the rebrand: replaced


def managed_labels() -> dict[str, str]:
    """The labels that mark a container or network as Kiboto's: the new one and, until 2.2, the old."""
    from backend import product

    return {product.MANAGED_LABEL: "1", OLD_MANAGED_LABEL: "1"}


def is_managed(labels: dict | None) -> bool:
    from backend import product

    labels = labels or {}
    return labels.get(product.MANAGED_LABEL) == "1" or labels.get(OLD_MANAGED_LABEL) == "1"


def follow_tag_labels() -> dict[str, str]:
    from backend import product

    return {product.FOLLOW_TAG_LABEL: "1", OLD_FOLLOW_TAG_LABEL: "1"}


def follows_tag(labels: dict | None) -> bool:
    from backend import product

    labels = labels or {}
    return labels.get(product.FOLLOW_TAG_LABEL) == "1" or labels.get(OLD_FOLLOW_TAG_LABEL) == "1"


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
