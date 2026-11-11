"""SET-14 VMs finding 27: a failed virtual machine action says what failed and a plain cause, not one generic sentence."""

import subprocess
from unittest.mock import patch

from backend.api import vms
from backend.errors import GENERIC_500


def test_a_plain_cause_is_said():
    err = vms._vm_failure("The disk was not resized", OSError(28, "No space left on device"))
    assert err.status_code == 500
    assert err.detail == "The disk was not resized: no space left on device."


def test_tool_output_is_kept_in_the_log_only():
    e = subprocess.CalledProcessError(1, ["qemu-img"], stderr="qemu-img: /data/vms/x/disk.qcow2: weird internal thing")
    err = vms._vm_failure("The disk was not resized", e)
    assert err.detail == "The disk was not resized. The details are in the server log."
    assert "/data/vms" not in err.detail


def test_the_route_answers_with_the_sentence_not_the_generic_one(client, auth_headers):
    with patch("backend.services.app_backup.list_vm_backups", side_effect=OSError(13, "Permission denied")):
        res = client.get("/api/vms/backups", headers=auth_headers)
    assert res.status_code == 500
    assert res.json()["detail"] == "The backups could not be listed: permission denied."
    assert res.json()["detail"] != GENERIC_500
