#!/usr/bin/env python3
"""
ZettNAS Toolkit - rclone WebDAV Auth Proxy.
Authenticates incoming WebDAV requests dynamically using ZettNAS SQLite User Store.
Mounts isolated home directories for standard users, and full pool for admins.
"""

import json
import os
import sys

# Ensure repository root is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend import config
from backend.passwords import verify_password
from backend.users_db import get_user_by_username


def main():
    try:
        raw = sys.stdin.read()
        if not raw:
            sys.exit(1)
        req = json.loads(raw)
    except Exception:
        sys.exit(1)

    username = str(req.get("user") or "").strip()
    password = str(req.get("pass") or "")

    if not username:
        sys.exit(1)

    # 1. Check user in SQLite users.db
    db_path = os.environ.get("USERS_DB_PATH") or getattr(config, "USERS_DB_PATH", None)
    user = get_user_by_username(username, db_path=db_path)
    authenticated = False
    is_admin = False

    if user and user.get("status") == "active":
        if verify_password(password, user.get("password_hash", "")):
            authenticated = True
            is_admin = user.get("role_id") in ("superadmin", "storage_admin")

    # 2. Fallback check for legacy admin credentials
    if not authenticated and username.lower() in ("admin", getattr(config, "ZETTNAS_USERNAME", "admin").lower()):
        if verify_password(password, config.STORED_PASSWORD_HASH) or password == (config.WEB_PASSWORD or "admin"):
            authenticated = True
            is_admin = True

    if not authenticated:
        sys.exit(1)

    # 3. Determine root path
    pool_path = getattr(config, "POOL_PATH", "/mnt/user")
    if is_admin:
        root = pool_path
    else:
        root = user.get("home_directory") if user else ""
        if not root:
            root = os.path.join(pool_path, "homes", username.lower())

    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        pass

    # 4. Output rclone backend configuration
    backend_config = {
        "type": "local",
        "_root": root,
    }
    sys.stdout.write(json.dumps(backend_config))
    sys.stdout.flush()
    sys.exit(0)


if __name__ == "__main__":
    main()
