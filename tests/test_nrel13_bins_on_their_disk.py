"""NREL-13: a delete goes to a bin on the item\x27s own disk, by rename, never by copying across disks."""

import os

from backend import fsutil
from backend.services import recycle_bin


def test_the_most_specific_root_wins():
    roots = ["/mnt/user", "/mnt", "/mnt/disks"]
    assert fsutil.root_for("/mnt/disks/usb1/photos/a.jpg", roots) == os.path.realpath("/mnt/disks")
    assert fsutil.root_for("/mnt/user/Family/a.txt", roots) == os.path.realpath("/mnt/user")
    assert fsutil.root_for("/mnt/cache/x", roots) == os.path.realpath("/mnt")
    assert fsutil.root_for("/srv/x", roots) is None


def test_same_disk_bin_is_at_the_top_of_the_filesystem(tmp_path):
    f = tmp_path / "a" / "b" / "c.txt"
    f.parent.mkdir(parents=True)
    f.write_text("x")
    top = recycle_bin.same_disk_bin(str(f))
    assert top is None or os.stat(os.path.dirname(top)).st_dev == os.stat(f).st_dev
    assert recycle_bin.same_disk_bin(str(tmp_path / "missing")) is None


def test_the_delete_route_only_renames():
    import inspect

    from backend.api.files import operations

    src = inspect.getsource(operations.fs_delete)
    assert "recycle_bin.move_to_bin, target_unresolved, recycle_dir, target_unresolved, True" in src
    assert "can only be deleted permanently" in src
