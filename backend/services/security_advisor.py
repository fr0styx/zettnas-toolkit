"""
ZettNAS Toolkit - Security Posture Advisor Engine
Evaluates live system security posture across authentication, multi-factor,
transport encryption, network file sharing, and API credentials.
Computes a real-time security score (0-100), letter grade (A-F), and actionable remediation plan.
"""

import time
from typing import Any, Dict, List, Optional
from fastapi import Request

import backend.config as config
from backend.config import is_using_default_password, logger
from backend.users_db import users_db_session


def evaluate_security_posture(request: Optional[Request] = None) -> Dict[str, Any]:
    """
    Evaluates the current security posture of the ZettNAS Toolkit instance.
    Returns:
        score: int (0-100)
        grade: str ('A', 'B', 'C', 'D', 'F')
        status: str ('secure', 'good', 'warning', 'critical')
        checks: List[Dict] with pass/fail status and weights
        issues: List[Dict] of actionable security findings
        evaluated_at: float (unix timestamp)
    """
    now = time.time()
    checks: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []

    # 1. Default Password Check (Weight: 35)
    def_pwd_active = is_using_default_password()
    checks.append(
        {
            "id": "default_password",
            "name": "Default Administrator Password",
            "category": "Authentication",
            "passed": not def_pwd_active,
            "penalty": 35 if def_pwd_active else 0,
            "severity": "critical" if def_pwd_active else "info",
            "details": "Default 'admin' password detected" if def_pwd_active else "Custom administrator password set",
        }
    )
    if def_pwd_active:
        issues.append(
            {
                "id": "sec-issue-default-password",
                "title": "Default Administrator Password Active",
                "severity": "critical",
                "description": "The default password ('admin') is still active for your administrator account. Anyone on your local network can access and control your NAS.",
                "remediation": "Change your administrator password immediately via Settings > Users & Security or the Setup Wizard.",
                "action_url": "#action:open-setup-wizard",
            }
        )

    # 2. Administrator 2FA / TOTP Check (Weight: 15)
    admin_mfa_active = False
    try:
        with users_db_session() as conn:
            admins = conn.execute(
                "SELECT id, username, mfa_enabled FROM users WHERE role_id IN ('superadmin', 'admin')"
            ).fetchall()
            if admins:
                admin_mfa_active = any(bool(a["mfa_enabled"]) for a in admins)
    except Exception as e:
        logger.debug(f"[SecurityAdvisor] Failed checking admin MFA: {e}")

    checks.append(
        {
            "id": "admin_mfa",
            "name": "Administrator Two-Factor Authentication (2FA)",
            "category": "Authentication",
            "passed": admin_mfa_active,
            "penalty": 0 if admin_mfa_active else 15,
            "severity": "high" if not admin_mfa_active else "info",
            "details": "Admin TOTP 2FA enabled" if admin_mfa_active else "Admin accounts lack two-factor protection",
        }
    )
    if not admin_mfa_active:
        issues.append(
            {
                "id": "sec-issue-admin-mfa",
                "title": "Two-Factor Authentication Not Configured",
                "severity": "high",
                "description": "Administrator accounts do not have multi-factor authentication (TOTP) enabled. In the event of credential leaks, accounts are vulnerable.",
                "remediation": "Enable TOTP Two-Factor Authentication in the Users & Security management tab.",
                "action_url": "#action:open-users-mfa",
            }
        )

    # 3. HTTPS / TLS Reverse Proxy Transport Encryption (Weight: 15)
    is_https = False
    if getattr(config, "ENABLE_PROXY_SSO", False):
        is_https = True
    elif request:
        proto = request.headers.get("x-forwarded-proto", "").lower()
        ssl_header = request.headers.get("x-forwarded-ssl", "").lower()
        if proto == "https" or ssl_header == "on" or request.url.scheme == "https":
            is_https = True

    checks.append(
        {
            "id": "https_transport",
            "name": "HTTPS Transport Encryption",
            "category": "Network",
            "passed": is_https,
            "penalty": 0 if is_https else 15,
            "severity": "medium" if not is_https else "info",
            "details": "Encrypted HTTPS / Reverse Proxy connection active"
            if is_https
            else "Unencrypted HTTP session in use",
        }
    )
    if not is_https:
        issues.append(
            {
                "id": "sec-issue-https-transport",
                "title": "Unencrypted HTTP Transport",
                "severity": "medium",
                "description": "Session traffic and login credentials travel over plain HTTP. Passwords could be intercepted over unencrypted local networks or Wi-Fi.",
                "remediation": "Place ZettNAS behind an SSL reverse proxy (e.g., Nginx, Caddy, Cloudflare Tunnel, or Traefik) and access via HTTPS.",
                "action_url": "https://github.com/fr0styx/zettnas-toolkit/blob/main/docs/INSTALLATION.md#reverse-proxy-sso",
            }
        )

    # 4. SMB Anonymous / Guest Access Check (Weight: 20)
    has_guest_shares = False
    guest_share_names: List[str] = []
    try:
        from backend.services.samba_engine import get_samba_engine

        engine = get_samba_engine()
        shares = engine.get_shares()
        for s_name, share in shares.items():
            if getattr(share, "guest_ok", False):
                has_guest_shares = True
                guest_share_names.append(s_name)
    except Exception as e:
        logger.debug(f"[SecurityAdvisor] Failed checking SMB guest shares: {e}")

    checks.append(
        {
            "id": "smb_guest_access",
            "name": "SMB Network Share Guest Access",
            "category": "Storage & Shares",
            "passed": not has_guest_shares,
            "penalty": 20 if has_guest_shares else 0,
            "severity": "high" if has_guest_shares else "info",
            "details": f"Guest shares detected: {', '.join(guest_share_names)}"
            if has_guest_shares
            else "All SMB shares require authenticated credentials",
        }
    )
    if has_guest_shares:
        issues.append(
            {
                "id": "sec-issue-smb-guest",
                "title": "Unauthenticated SMB Guest Shares Detected",
                "severity": "high",
                "description": f"The following shares allow unauthenticated guest access: {', '.join(guest_share_names)}. Any device on your LAN can read/write data without a password.",
                "remediation": "Edit your SMB share configurations in Storage Management and uncheck 'Allow Guest Access'.",
                "action_url": "#action:open-storage-shares",
            }
        )

    # 5. Stale API Tokens Check (Weight: 15)
    stale_token_count = 0
    stale_threshold = now - (90 * 86400)
    try:
        with users_db_session() as conn:
            tok_rows = conn.execute("SELECT token_id, name, created_at, last_used_at FROM api_tokens").fetchall()
            for r in tok_rows:
                created = float(r["created_at"] or 0)
                last_used = float(r["last_used_at"]) if r["last_used_at"] else None
                # Token created > 90 days ago and never used, or not used in > 90 days
                if created < stale_threshold:
                    if last_used is None or last_used < stale_threshold:
                        stale_token_count += 1
    except Exception as e:
        logger.debug(f"[SecurityAdvisor] Failed checking stale API tokens: {e}")

    checks.append(
        {
            "id": "stale_api_tokens",
            "name": "API Token Hygiene",
            "category": "Credentials",
            "passed": stale_token_count == 0,
            "penalty": 15 if stale_token_count > 0 else 0,
            "severity": "low" if stale_token_count > 0 else "info",
            "details": f"{stale_token_count} stale API token(s) detected (>90 days inactive)"
            if stale_token_count > 0
            else "API access tokens are clean and active",
        }
    )
    if stale_token_count > 0:
        issues.append(
            {
                "id": "sec-issue-stale-tokens",
                "title": f"Stale API Tokens ({stale_token_count} Detected)",
                "severity": "low",
                "description": f"{stale_token_count} API tokens have not been used in over 90 days. Dormant tokens widen the attack surface if compromised.",
                "remediation": "Revoke unused tokens in Users & Security > API Tokens.",
                "action_url": "#action:open-api-tokens",
            }
        )

    # Total Score Calculation
    total_penalty = sum(c["penalty"] for c in checks)
    score = max(0, min(100, 100 - total_penalty))

    if score >= 90:
        grade = "A"
        status = "secure"
    elif score >= 75:
        grade = "B"
        status = "good"
    elif score >= 60:
        grade = "C"
        status = "warning"
    elif score >= 40:
        grade = "D"
        status = "warning"
    else:
        grade = "F"
        status = "critical"

    return {
        "score": score,
        "grade": grade,
        "status": status,
        "checks": checks,
        "issues": issues,
        "evaluated_at": now,
    }
