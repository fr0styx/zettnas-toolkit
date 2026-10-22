#!/usr/bin/env python3
"""Nightly copy of the family photo library to the USB backup drive."""

import datetime
import shutil
import subprocess
from pathlib import Path

SRC = Path("/mnt/user/photos")
DEST = Path("/mnt/disks/usb_backup/photos")


def main():
    if not DEST.parent.exists():
        print("USB backup drive is not plugged in; skipping")
        return
    started = datetime.datetime.now()
    subprocess.run(["rsync", "-a", "--delete", f"{SRC}/", f"{DEST}/"], check=True)
    free = shutil.disk_usage(DEST).free // 2**30
    print(f"photo backup finished in {datetime.datetime.now() - started}, {free} GiB free")


if __name__ == "__main__":
    main()
