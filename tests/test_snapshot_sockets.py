"""Pre-update snapshots skip sockets (Samba keeps live sockets under data/samba/private)."""

import os
import socket

from backend.services import data_snapshot


def test_snapshot_skips_sockets(tmp_path):
    data = tmp_path / "data"
    sock_dir = data / "samba" / "private" / "msg.sock"
    sock_dir.mkdir(parents=True)
    (data / "samba" / "smb.conf").write_text("[global]\n")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(sock_dir / "29"))
    try:
        dest = data_snapshot.take_snapshot(str(data), label="test")
    finally:
        s.close()
    assert os.path.exists(os.path.join(dest, "samba", "smb.conf"))
    assert not os.path.exists(os.path.join(dest, "samba", "private", "msg.sock", "29"))
