"""
Sign in with LDAP or Active Directory (M6).

A service account looks the user up (sAMAccountName, uid or mail), then ZettNAS binds
as that user with the password they typed. The directory never sees ZettNAS's own
passwords, and ZettNAS never stores the directory password.

Accounts: the user's DN is stored on the ZettNAS account (idp_type "ldap"). A local
account with the same name keeps signing in with its local password; an LDAP login never
takes it over. Roles come from groups (memberOf): admin_groups -> SuperAdmin, role_map
for others, default_role otherwise, re-applied at each sign-in when sync_roles is on.

Use ldaps:// or StartTLS. Empty passwords are refused (an empty password would be an
anonymous bind, which many servers accept).
"""

import json
import os
import secrets
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked

CONFIG_FILE = os.path.join(DATA_DIR, "ldap.json")
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "server_url": "",
    "start_tls": False,
    "verify_tls": True,
    "bind_dn": "",
    "bind_password": "",
    "base_dn": "",
    "user_filter": "(|(sAMAccountName={username})(uid={username})(userPrincipalName={username})(mail={username}))",
    "username_attr": "",
    "admin_groups": [],
    "role_map": {},
    "default_role": "share_user",
    "auto_create": True,
    "sync_roles": True,
    "timeout": 8,
}
_SERVER_FACTORY = None  # tests replace this with an ldap3 MOCK server


class LdapError(Exception):
    pass


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError):
        logger.debug("ldap: no saved config", exc_info=False)
    return cfg


def enabled() -> bool:
    c = load_config()
    return bool(c["enabled"] and c["server_url"] and c["base_dn"])


def masked_config() -> dict[str, Any]:
    cfg = load_config()
    cfg["bind_password"] = "********" if cfg.get("bind_password") else ""
    return cfg


@json_locked(lambda *a, **k: CONFIG_FILE)
def save_config(changes: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    for k, v in changes.items():
        if k in DEFAULTS and v is not None and not (k == "bind_password" and v == "********"):
            cfg[k] = v
    url = str(cfg.get("server_url") or "").strip()
    if url and not url.lower().startswith(("ldap://", "ldaps://")):
        raise LdapError("The server must be an ldap:// or ldaps:// address")
    if "{username}" not in str(cfg.get("user_filter") or ""):
        raise LdapError("The user filter must contain {username}")
    cfg["server_url"] = url
    cfg["admin_groups"] = [str(g) for g in cfg.get("admin_groups") or []]
    cfg["role_map"] = {str(k): str(v) for k, v in (cfg.get("role_map") or {}).items()}
    atomic_write_json(CONFIG_FILE, cfg, indent=1)  # owner-only (0600)
    return masked_config()


def _server(cfg: dict[str, Any]):
    if _SERVER_FACTORY:
        return _SERVER_FACTORY(cfg)
    import ssl

    from ldap3 import Server, Tls

    tls = Tls(validate=ssl.CERT_REQUIRED if cfg.get("verify_tls", True) else ssl.CERT_NONE)
    return Server(
        cfg["server_url"],
        use_ssl=cfg["server_url"].lower().startswith("ldaps://"),
        tls=tls,
        connect_timeout=int(cfg.get("timeout") or 8),
    )


def _connection(server, user: str | None, password: str | None, cfg: dict[str, Any]):
    from ldap3 import Connection

    kwargs: dict[str, Any] = {"receive_timeout": int(cfg.get("timeout") or 8)}
    if _SERVER_FACTORY:
        kwargs = {"client_strategy": "MOCK_SYNC"}
    conn = Connection(server, user=user, password=password, raise_exceptions=False, **kwargs)
    if cfg.get("start_tls") and not _SERVER_FACTORY:
        conn.open()
        conn.start_tls()
    return conn


def _cn(dn: str) -> str:
    first = str(dn).split(",", 1)[0]
    return first.split("=", 1)[1] if "=" in first else first


def find_user(username: str, cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    from ldap3.utils.conv import escape_filter_chars

    cfg = cfg or load_config()
    server = _server(cfg)
    svc = _connection(server, cfg.get("bind_dn") or None, cfg.get("bind_password") or None, cfg)
    if not svc.bind():
        raise LdapError("The service account could not sign in to the directory")
    try:
        flt = cfg["user_filter"].replace("{username}", escape_filter_chars(username))
        svc.search(cfg["base_dn"], flt, attributes=["*", "memberOf"], size_limit=2)
        entries = list(svc.entries)
        if len(entries) != 1:
            return None  # unknown, or ambiguous: never guess
        e = entries[0]
        attrs = e.entry_attributes_as_dict
        group_dns = [str(g) for g in attrs.get("memberOf") or []]
        if not group_dns:
            # OpenLDAP, FreeIPA and Synology often have no memberOf: ask the groups instead
            uid = str((attrs.get("uid") or [username])[0])
            gflt = (
                f"(|(member={escape_filter_chars(e.entry_dn)})(uniqueMember={escape_filter_chars(e.entry_dn)})"
                f"(memberUid={escape_filter_chars(uid)}))"
            )
            svc.search(cfg["base_dn"], gflt, attributes=["cn"], size_limit=200)
            group_dns = [g.entry_dn for g in svc.entries]
    finally:
        svc.unbind()

    def first(*names):
        for n in names:
            v = attrs.get(n)
            if v:
                return str(v[0] if isinstance(v, list) else v)
        return ""

    groups = group_dns
    return {
        "dn": e.entry_dn,
        "username": first(cfg.get("username_attr") or "sAMAccountName", "uid", "sAMAccountName") or username,
        "name": first("displayName", "cn"),
        "email": first("mail", "userPrincipalName"),
        "groups": groups + [_cn(g) for g in groups],
    }


def check_password(dn: str, password: str, cfg: dict[str, Any] | None = None) -> bool:
    if not password:
        return False  # an empty password would be an anonymous bind
    cfg = cfg or load_config()
    conn = _connection(_server(cfg), dn, password, cfg)
    try:
        return bool(conn.bind())
    finally:
        try:
            conn.unbind()
        except Exception:
            logger.debug("ldap: unbind failed", exc_info=True)


def role_for(groups: list[str], cfg: dict[str, Any]) -> str:
    low = {g.lower() for g in groups}
    if any(str(a).lower() in low for a in cfg.get("admin_groups") or []):
        return "superadmin"
    for g, role in (cfg.get("role_map") or {}).items():
        if g.lower() in low:
            return role
    return cfg.get("default_role") or "share_user"


def login(username: str, password: str) -> dict[str, Any] | None:
    """The ZettNAS user for these directory credentials, or None."""
    from backend.users_db import create_user, get_user_by_idp, get_user_by_username, update_user_profile

    if not enabled() or not username or not password:
        return None
    cfg = load_config()
    try:
        info = find_user(username, cfg)
        if not info or not check_password(info["dn"], password, cfg):
            return None
    except LdapError:
        raise
    except Exception as e:
        logger.warning(f"[LDAP] Directory unreachable: {e}")
        return None
    role = role_for(info["groups"], cfg)
    user = get_user_by_idp("ldap", info["dn"])
    if not user:
        local = get_user_by_username(info["username"].lower())
        if local and local.get("idp_type") not in ("ldap",):
            logger.warning(f"[LDAP] '{info['username']}' is a local account; not linking it to the directory")
            return None
        if not cfg.get("auto_create", True):
            return None
        created = create_user(
            username=info["username"].lower()[:32],
            display_name=(info["name"] or info["username"])[:64],
            password=secrets.token_urlsafe(32),
            email=info["email"],
            role_id=role,
            idp_type="ldap",
            idp_sub=info["dn"],
        )
        user = get_user_by_username(created["username"])
    elif cfg.get("sync_roles", True) and user.get("role_id") != role:
        try:
            update_user_profile(user["id"], role_id=role)
            user = get_user_by_username(user["username"]) or user
        except Exception:
            logger.warning("[LDAP] Could not update the role (last SuperAdmin?)", exc_info=True)
    return user


def test_connection() -> dict[str, Any]:
    cfg = load_config()
    try:
        conn = _connection(_server(cfg), cfg.get("bind_dn") or None, cfg.get("bind_password") or None, cfg)
        ok = bool(conn.bind())
        conn.unbind()
        return {"ok": ok, "message": "Connected" if ok else "The service account was refused"}
    except Exception as e:
        return {"ok": False, "message": str(e)[:200]}
