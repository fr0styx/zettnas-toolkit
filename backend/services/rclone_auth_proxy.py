#!/usr/bin/env python3
"""
ZettNAS Toolkit - rclone WebDAV & SFTP Auth Proxy.
Authenticates incoming WebDAV/SFTP requests dynamically using:
1. Dedicated SFTP User Store (data/sftp/users.json)
2. ZettNAS SQLite User Store (users.db)
No default or legacy admin password is ever accepted (SEC-02). Accounts that
still have to change their password, and usernames locked out after repeated
failures, are refused.
Mounts isolated home directories or designated shares for standard users, and full pool for admins.
"""

import hmac
import json
import os
import re
import sys
import tempfile

# Ensure repository root is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import logging

from backend import config
from backend.fsutil import safe_serve_root
from backend.ignored_errors import ignored
from backend.passwords import verify_password
from backend.services import login_lockout
from backend.users_db import get_user_by_username

logger = logging.getLogger("ZettNAS")


def _is_hash(stored: str) -> bool:
    return stored.startswith(("$argon2", "scrypt$")) or bool(re.fullmatch(r"[0-9a-f]{64}", stored))


def _sftp_password_ok(stored: str, password: str) -> bool:
    """Hashed entries are checked as hashes; plain comparison only for entries saved before hashing."""
    if not stored or not password:
        return False
    if _is_hash(stored):
        return verify_password(password, stored)
    return hmac.compare_digest(stored, password)


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
    public_key = str(req.get("public_key") or "").strip()

    if not username:
        sys.exit(1)

    lock_key = f"webdav:{username.lower()}"
    if login_lockout.remaining(lock_key) > 0:
        sys.exit(1)

    pool_path = getattr(config, "POOL_PATH", "/mnt/user")
    authenticated = False
    is_admin = False
    is_read_only = False
    target_root = None

    # 1. Check dedicated SFTP User Store (data/sftp/users.json)
    sftp_users_file = os.path.join(getattr(config, "DATA_DIR", "/app/data"), "sftp", "users.json")
    if os.path.exists(sftp_users_file):
        try:
            with open(sftp_users_file, encoding="utf-8") as f:
                sftp_users = json.load(f)
            if isinstance(sftp_users, list):
                for u in sftp_users:
                    if u.get("username", "").strip().lower() == username.lower() and u.get("enabled", True):
                        if _sftp_password_ok(str(u.get("password") or ""), password):
                            authenticated = True
                        u_key = str(u.get("pubkey") or "").strip()
                        if u_key and public_key:
                            u_parts = u_key.split()[:2]
                            p_parts = str(public_key).strip().split()[:2]
                            if u_parts and u_parts == p_parts:
                                authenticated = True
                        if authenticated:
                            is_read_only = bool(u.get("read_only", False))
                            # only folders the serve rules allow; an account left with none is refused
                            shares = [
                                r
                                for r in (
                                    safe_serve_root(s if os.path.isabs(s) else os.path.join(pool_path, s), pool_path)
                                    for s in u.get("shares", [])
                                )
                                if r
                            ]
                            if u.get("shares") and not shares:
                                authenticated = False
                                break
                            if len(shares) == 1:
                                target_root = shares[0]
                            elif len(shares) > 1:
                                # outside the data folder: the chroot holds only links to the shares
                                user_chroot = os.path.join(
                                    tempfile.gettempdir(), "zettnas-sftp-chroot", username.lower()
                                )
                                os.makedirs(user_chroot, mode=0o700, exist_ok=True)
                                for entry in os.listdir(user_chroot):
                                    link_p = os.path.join(user_chroot, entry)
                                    if os.path.islink(link_p) or os.path.isfile(link_p):
                                        try:
                                            os.unlink(link_p)
                                        except OSError:
                                            pass
                                for s in shares:
                                    target_s = s if os.path.isabs(s) else os.path.join(pool_path, s)
                                    share_name = os.path.basename(s.rstrip("/\\"))
                                    if os.path.exists(target_s):
                                        link_target = os.path.join(user_chroot, share_name)
                                        try:
                                            os.symlink(target_s, link_target)
                                        except OSError:
                                            pass
                                target_root = user_chroot
                            else:
                                target_root = os.path.join(pool_path, "homes", username.lower())
                            break
        except Exception:
            ignored("backend.services.rclone_auth_proxy.main")

    # 2. Check user in SQLite users.db
    if not authenticated:
        db_path = os.environ.get("USERS_DB_PATH") or getattr(config, "USERS_DB_PATH", None)
        user = get_user_by_username(username, db_path=db_path)
        # WebDAV and SFTP have no second-factor step, so accounts with two-factor sign-in
        # use a dedicated SFTP/WebDAV account instead of their ZettNAS password.
        if (
            user
            and user.get("status") == "active"
            and not user.get("must_change_password")
            and not user.get("mfa_enabled")
        ):
            if password and verify_password(password, user.get("password_hash", "")):
                authenticated = True
                is_admin = user.get("role_id") in ("superadmin", "storage_admin")
                is_read_only = user.get("role_id") == "guest"
                if is_admin:
                    target_root = pool_path
                else:
                    target_root = user.get("home_directory") or os.path.join(pool_path, "homes", username.lower())

    if not authenticated:
        login_lockout.register_failure(lock_key)
        sys.exit(1)
    login_lockout.clear(lock_key)

    # 4. Resolve root path safely: never the data folder or a folder holding it (SEC-20)
    root = target_root or pool_path
    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        pass
    if not os.path.exists(root):
        root = pool_path
    chroot_base = os.path.join(tempfile.gettempdir(), "zettnas-sftp-chroot")
    if not root.startswith(chroot_base + os.sep) and safe_serve_root(root, pool_path) is None:
        login_lockout.register_failure(lock_key)
        sys.exit(1)

    # 5. Output rclone backend configuration
    backend_config = {
        "type": "local",
        "_root": root,
    }
    if is_read_only:
        backend_config["_read_only"] = True
    sys.stdout.write(json.dumps(backend_config))
    sys.stdout.flush()
    sys.exit(0)


if __name__ == "__main__":
    main()
