"""Names from before the Kiboto rebrand (ZettNAS) that the code still has to know.

Accepted until Kiboto 2.2 (REMOVE_IN), then removed with this file: the ZETTNAS_* environment
variables existing installs set, and the other old names added here as the rename goes on.

Kept for good, elsewhere and on purpose, because data made before depends on them: the data key's
salt (db_crypto._KDF_SALT), the two-factor secret box's key and associated data (secret_box), the
backup manifest name and config-export prefix that restores still read (backup_engine), and the
restic tag on off-site snapshots (offsite_backup). Changing those would make that data unreadable.
The same goes for names stored outside Kiboto's data: replication's ZFS snapshot names
(zettnas-repl-, the next incremental send's base), the encrypted-dataset and data-id properties,
the snapshot views, WORM and version folders, the NFS exports file, the fan watchdog's heartbeat
file (its own contract), the secrets file, the restic location backup_migration made
(zettnas-restic), the family calendar's DAV identity, the RAG schema's embedding id, the WebDAV
fallback secret (tokens signed with it), the recovery-code hash prefix, the restic host id, VM serial
sockets in saved VM definitions, the apps' .zettnas-secrets.json, the backup versions and dump names,
and outside the app: the hardware runner's label (set on the runner), the deployed health worker's
names, and the alert webhook's event name (zettnas_alert, which automations match on).
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
OLD_APP_CONTAINER_NAMES = ("zettnas-toolkit", "zettnas", "zettnas_toolkit")
OLD_ROLLBACK_REPO = "zettnas-toolkit-rollback"  # rollback images tagged before keep their tag
OLD_HOST_APPDATA = "/mnt/user/appdata/zettnas-toolkit"  # Unraid's appdata folder on installs made before
OLD_MODEL_SERVERS = ("zettnas-ollama", "zettnas-ovms")
OLD_SESSION_COOKIE = "zettnas_session"  # browsers signed in before the rebrand still send it
OLD_CANARY_NAME = "!ZettNAS-guard-file.docx"  # the ransomware guard's file before the rebrand
OLD_NAS_NAME = "zettnas"  # zettnas.local keeps answering beside kiboto.local (D17)
OLD_NAME_CONTAINER = "zettnas-name"  # the name responder's container before the rebrand: replaced
OLD_PART_SUFFIX = ".zettnas-part"  # a half-copied file left by a transfer before the rebrand: swept
OLD_STAGE_INFIX = ".zettnas-stage-"  # a move's staging folder from before the rebrand: swept
OLD_METRIC_PREFIX = "zettnas_"  # /api/metrics repeats every kiboto_ series under this prefix
OLD_BACKUP_TAG = "zettnas"  # the restic tag on every off-site file backup: existing ones carry it, so it stays
OLD_KIB_STATUS_KEY = "zettai_status"  # the Kib status answer repeats "kib_status" under this key
OLD_LOG_FILE = "zettnas.log"  # the log file and its rotations carry on under the new name


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


def app_container_names() -> tuple[str, ...]:
    """Kiboto's own container: kiboto, or a name from before the rebrand."""
    from backend import product

    return (product.CONTAINER, *OLD_APP_CONTAINER_NAMES)


def is_app_container(name: str | None) -> bool:
    return str(name or "").lstrip("/").lower() in app_container_names()


def with_old_metric_names(text: str) -> str:
    """Prometheus text with every kiboto_ series (and its HELP/TYPE) repeated under zettnas_, so
    dashboards and alerts made before the rebrand keep working until 2.2."""
    old = []
    for line in text.splitlines():
        for head in ("kiboto_", "# HELP kiboto_", "# TYPE kiboto_"):
            if line.startswith(head):
                old.append(line.replace("kiboto_", OLD_METRIC_PREFIX, 1))
                break
    return text + ("\n".join(old) + "\n" if old else "")


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
