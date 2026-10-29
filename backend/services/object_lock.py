"""A locked cloud copy: off-site backups into a bucket with Object Lock (FEAT-03, COMP-09).

With Object Lock (Backblaze B2 calls it File Lock) every write is kept for the bucket's
retention period. A delete, by restic or by someone holding this NAS's keys, only hides the
newest version; the locked versions stay and can be brought back until the period ends. restic
works unchanged; ZettNAS keeps every version inside the period (forget --keep-within), shows how
long the newest copy is locked, and asks the provider whether the bucket really is locked:
Backblaze through its own API, Amazon S3, Wasabi and other S3 services with a signed
GET ?object-lock. Only the bucket's settings are read; nothing is written.
"""

from __future__ import annotations

import base64
import configparser
import datetime as dt
import hashlib
import hmac
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

from backend.config import RCLONE_CONFIG_FILE

B2_AUTH_URL = "https://api.backblazeb2.com/b2api/v3/b2_authorize_account"
MAX_DAYS = 3650

PRESETS: dict[str, dict[str, Any]] = {
    "b2": {
        "name": "Backblaze B2",
        "rclone_type": "b2",
        "steps": [
            "Create a bucket with File Lock turned on (it can only be chosen when the bucket is made).",
            "Set the bucket's default retention: Compliance mode, for example 30 days.",
            "Add a lifecycle rule that keeps only the last version, so hidden versions go once their lock ends.",
            "Create an application key for that bucket and add it in Cloud Drives as a b2 remote.",
        ],
    },
    "wasabi": {
        "name": "Wasabi",
        "rclone_type": "s3",
        "steps": [
            "Create a bucket with Object Locking turned on (only possible when the bucket is made).",
            "Set the default retention: Compliance mode, for example 30 days.",
            "Create an access key and add it in Cloud Drives as an s3 remote, provider Wasabi, "
            "with the endpoint of the bucket's region (s3.<region>.wasabisys.com).",
        ],
    },
    "s3": {
        "name": "Amazon S3",
        "rclone_type": "s3",
        "steps": [
            "Create a bucket with Object Lock enabled (this also turns on versioning).",
            "Set a default retention rule: Compliance mode, for example 30 days.",
            "Add a lifecycle rule that expires noncurrent versions a day after the lock ends.",
            "Create an access key limited to that bucket and add it in Cloud Drives as an s3 remote.",
        ],
    },
    "other": {
        "name": "Another S3 service",
        "rclone_type": "s3",
        "steps": [
            "Create a bucket with Object Lock and a default retention in Compliance mode.",
            "Add it in Cloud Drives as an s3 remote with the service's endpoint.",
        ],
    },
}


class LockCheckError(Exception):
    """The bucket's lock could not be read; the message says why."""


def presets() -> list[dict[str, Any]]:
    return [{"id": k, **v} for k, v in PRESETS.items()]


def lock_days(value: Any) -> int:
    try:
        return max(0, min(int(value or 0), MAX_DAYS))
    except (TypeError, ValueError):
        raise ValueError("The lock period is a number of days.") from None


def locked_until(repo: dict[str, Any]) -> float | None:
    """When the newest backup's lock ends: its time plus the lock period."""
    days = int(repo.get("lock_days") or 0)
    last = repo.get("last_backup")
    if not days or not last:
        return None
    return float(last) + days * 86400


def remote_of(location: str) -> tuple[str, str]:
    """(remote, bucket) for rclone:remote:bucket/path."""
    m = re.fullmatch(r"rclone:([^:]+):/?([^/]+)(?:/.*)?", location or "")
    if not m:
        raise LockCheckError("A locked copy goes to a cloud remote: rclone:remote:bucket/folder.")
    return m.group(1), m.group(2)


def remote_settings(remote: str, path: str = RCLONE_CONFIG_FILE) -> dict[str, str]:
    cp = configparser.RawConfigParser()
    try:
        cp.read(path, encoding="utf-8")
    except (OSError, configparser.Error) as e:
        raise LockCheckError(f"The cloud drive settings can't be read: {e}") from None
    if not cp.has_section(remote):
        raise LockCheckError(f"There is no cloud drive called {remote}.")
    return dict(cp.items(remote))


# --- Amazon S3 Signature Version 4, for one GET ---


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sigv4_headers(
    url: str,
    region: str,
    access_key: str,
    secret_key: str,
    now: dt.datetime,
    extra: dict[str, str] | None = None,
    service: str = "s3",
) -> dict[str, str]:
    """The headers that sign a GET of url (no body)."""
    u = urllib.parse.urlsplit(url)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = amz_date[:8]
    empty = _sha256(b"")
    headers = {"host": u.netloc, "x-amz-content-sha256": empty, "x-amz-date": amz_date}
    headers.update({k.lower(): v.strip() for k, v in (extra or {}).items()})
    signed = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
    query = urllib.parse.parse_qsl(u.query, keep_blank_values=True)
    canonical_query = "&".join(
        f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(v, safe='-_.~')}" for k, v in sorted(query)
    )
    path = urllib.parse.quote(u.path or "/", safe="/-_.~")
    canonical = "\n".join(["GET", path, canonical_query, canonical_headers, signed, empty])
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, _sha256(canonical.encode("utf-8"))])
    key = _hmac(_hmac(_hmac(_hmac(f"AWS4{secret_key}".encode(), day), region), service), "aws4_request")
    signature = hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        **{k: v for k, v in headers.items() if k != "host"},
        "Authorization": f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed}, Signature={signature}",
    }


def _open(req: urllib.request.Request, timeout: float = 15.0) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (the user's own cloud)
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _s3_endpoint(cfg: dict[str, str]) -> tuple[str, str]:
    region = (cfg.get("region") or "us-east-1").strip() or "us-east-1"
    endpoint = (cfg.get("endpoint") or "").strip()
    if not endpoint:
        endpoint = f"s3.{region}.amazonaws.com"
    if not endpoint.startswith(("http://", "https://")):
        endpoint = "https://" + endpoint
    return endpoint.rstrip("/"), region


def _parse_s3(status: int, body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace")
    if status == 404 or "ObjectLockConfigurationNotFound" in text:
        return {"enabled": False, "mode": None, "days": 0}
    if status == 403:
        raise LockCheckError("The key may not read the bucket's lock settings (GetBucketObjectLockConfiguration).")
    if status != 200:
        raise LockCheckError(f"The service answered {status}.")
    root = ET.fromstring(text)
    ns = re.match(r"\{.*\}", root.tag)
    p = ns.group(0) if ns else ""
    enabled = (root.findtext(f"{p}ObjectLockEnabled") or "") == "Enabled"
    mode = root.findtext(f".//{p}DefaultRetention/{p}Mode")
    days = root.findtext(f".//{p}DefaultRetention/{p}Days")
    years = root.findtext(f".//{p}DefaultRetention/{p}Years")
    total = int(days) if days else (int(years) * 365 if years else 0)
    return {"enabled": enabled, "mode": mode, "days": total}


def check_s3(
    cfg: dict[str, str], bucket: str, opener: Callable = _open, now: dt.datetime | None = None
) -> dict[str, Any]:
    endpoint, region = _s3_endpoint(cfg)
    access, secret = cfg.get("access_key_id") or "", cfg.get("secret_access_key") or ""
    if not access or not secret:
        raise LockCheckError("The s3 remote has no access key in its settings.")
    url = f"{endpoint}/{urllib.parse.quote(bucket)}?object-lock="
    headers = sigv4_headers(url, region, access, secret, now or dt.datetime.now(dt.UTC))
    return _parse_s3(*opener(urllib.request.Request(url, headers=headers)))


def check_b2(cfg: dict[str, str], bucket: str, opener: Callable = _open) -> dict[str, Any]:
    account, key = cfg.get("account") or "", cfg.get("key") or ""
    if not account or not key:
        raise LockCheckError("The b2 remote has no application key in its settings.")
    basic = base64.b64encode(f"{account}:{key}".encode()).decode()
    status, body = opener(urllib.request.Request(B2_AUTH_URL, headers={"Authorization": f"Basic {basic}"}))
    if status != 200:
        raise LockCheckError("Backblaze refused the application key.")
    auth = json.loads(body)
    api = ((auth.get("apiInfo") or {}).get("storageApi") or {}).get("apiUrl") or auth.get("apiUrl")
    req = urllib.request.Request(
        f"{api}/b2api/v3/b2_list_buckets",
        data=json.dumps({"accountId": auth.get("accountId"), "bucketName": bucket}).encode(),
        headers={"Authorization": auth.get("authorizationToken", ""), "Content-Type": "application/json"},
        method="POST",
    )
    status, body = opener(req)
    if status != 200:
        raise LockCheckError(f"Backblaze answered {status} for the bucket.")
    buckets = json.loads(body).get("buckets") or []
    if not buckets:
        raise LockCheckError(f"Backblaze has no bucket called {bucket} for this key.")
    lock = buckets[0].get("fileLockConfiguration") or {}
    if lock.get("isClientAuthorizedToRead") is False:
        raise LockCheckError("The application key may not read the bucket's File Lock settings (readBucketRetentions).")
    value = lock.get("value") or {}
    retention = value.get("defaultRetention") or {}
    period = retention.get("period") or {}
    n = int(period.get("duration") or 0)
    days = n * 365 if period.get("unit") == "years" else n
    mode = (retention.get("mode") or "") or None
    return {"enabled": bool(value.get("isFileLockEnabled")), "mode": mode.upper() if mode else None, "days": days}


def check(location: str, opener: Callable = _open, config_path: str = RCLONE_CONFIG_FILE) -> dict[str, Any]:
    """Whether the backup's bucket keeps every write for a while, read from the provider."""
    remote, bucket = remote_of(location)
    cfg = remote_settings(remote, config_path)
    kind = (cfg.get("type") or "").lower()
    if kind == "b2":
        result = check_b2(cfg, bucket, opener)
    elif kind == "s3":
        result = check_s3(cfg, bucket, opener)
    else:
        raise LockCheckError(
            f"{remote} is a {kind or 'unknown'} remote; Object Lock needs Backblaze B2 or an S3 service."
        )
    result["bucket"] = bucket
    result["ok"] = bool(result["enabled"] and result["days"])
    if result["enabled"] and not result["days"]:
        result["note"] = "Object Lock is on but the bucket has no default retention, so new files aren't locked."
    elif result["ok"] and result["mode"] == "GOVERNANCE":
        result["note"] = (
            "Governance mode: a key with the bypass right can still delete. Compliance mode can't be undone."
        )
    return result
