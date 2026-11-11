import io
import json
import os
import tempfile
import time
import zipfile

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.api.auth import _clear_failures, _failures, _lockout_remaining, _register_failure
from backend.api.system import _safe_fs_target, list_tokens
from backend.api_tokens import (
    TOKENS_FILE,
    load_tokens,
    revoke_token,
    save_tokens,
)
from backend.main import app
from backend.services.backup_engine import (
    BACKUP_EXCLUSIONS,
    generate_backup_zip_stream,
    restore_backup_archive,
)

client = TestClient(app)


def test_safe_fs_target_blocks_symlinks_outside_roots(tmp_path):
    """Verify that symlinks pointing outside allowed roots are blocked with 403."""
    from backend.config import ALLOWED_BROWSE_ROOTS

    valid_root = ALLOWED_BROWSE_ROOTS[0]
    os.makedirs(valid_root, exist_ok=True)

    # Create target outside allowed roots
    secret_dir = str(tmp_path / "secret_host_dir")
    os.makedirs(secret_dir, exist_ok=True)
    secret_file = os.path.join(secret_dir, "secret.txt")
    with open(secret_file, "w") as f:
        f.write("confidential")

    # Create symlink inside valid_root pointing to secret_file
    symlink_path = os.path.join(valid_root, "evil_symlink.txt")
    if os.path.lexists(symlink_path):
        os.unlink(symlink_path)
    os.symlink(secret_file, symlink_path)

    try:
        # Requesting evil_symlink.txt must be rejected with 403
        with pytest.raises(HTTPException) as exc_info:
            _safe_fs_target(symlink_path)
        assert exc_info.value.status_code == 403
        assert "outside allowed folders" in exc_info.value.detail.lower()
    finally:
        if os.path.lexists(symlink_path):
            os.unlink(symlink_path)


def test_backup_engine_symlink_rejection():
    """Verify restore_backup_archive rejects archives containing symlinks."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        # Create a member with symlink attribute
        zi = zipfile.ZipInfo("symlink_attack.txt")
        zi.create_system = 3  # Unix
        zi.external_attr = 0o120777 << 16  # S_IFLNK
        z.writestr(zi, "/etc/shadow")
    buf.seek(0)

    with pytest.raises(ValueError) as exc:
        restore_backup_archive(buf)
    assert "Symlinks are forbidden" in str(exc.value)


def test_backup_engine_size_and_member_limits():
    """Verify restore_backup_archive enforces file count and size ceilings."""
    # Test member count limit (>1000)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(1005):
            z.writestr(f"file_{i}.txt", "data")
    buf.seek(0)

    with pytest.raises(ValueError) as exc:
        restore_backup_archive(buf)
    assert "maximum allowable file count" in str(exc.value)


def test_backup_exclusions_include_api_tokens():
    """Verify api_tokens.json is excluded from backup archives."""
    assert "api_tokens.json" in BACKUP_EXCLUSIONS
    stream = generate_backup_zip_stream()
    with zipfile.ZipFile(stream, "r") as z:
        names = z.namelist()
        assert "api_tokens.json" not in names


def test_auth_rate_limiting_ttl_pruning():
    """Verify brute force failure tracker prunes expired entries when cache grows."""
    _clear_failures("test_ip_1")
    _register_failure("test_ip_1")
    assert _lockout_remaining("test_ip_1") >= 0

    # Simulate bloated _failures cache with expired items
    old_time = time.time() - 4000
    for i in range(1005):
        _failures[f"dummy_ip_{i}"] = {"count": 1, "locked_until": old_time, "last_seen": old_time}

    # Registering a failure should trigger pruning
    _register_failure("new_active_ip")
    assert len(_failures) < 500, "Expired failures must be pruned when cache exceeds 1000"
