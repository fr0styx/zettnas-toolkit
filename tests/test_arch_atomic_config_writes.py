"""Settings are written crash-safely: no raw json.dump to a file outside fsutil (ARCH-6)."""

import json
import os
import pathlib
import re

from backend.fsutil import atomic_write_json

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_no_raw_json_file_writes_in_the_backend():
    offenders = []
    for path in sorted((ROOT / "backend").rglob("*.py")):
        if path.name == "fsutil.py":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bjson\.dump\(", line):
                offenders.append(f"{path.relative_to(ROOT)}:{n}")
    assert offenders == [], "use backend.fsutil.atomic_write_json: " + ", ".join(offenders)


def test_atomic_write_keeps_the_old_file_when_writing_fails(tmp_path):
    target = tmp_path / "settings.json"
    atomic_write_json(str(target), {"a": 1}, indent=2)
    assert json.loads(target.read_text()) == {"a": 1} and "\n" in target.read_text()
    try:
        atomic_write_json(str(target), {"bad": object()})
    except TypeError:
        pass
    assert json.loads(target.read_text()) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]  # no temp file left behind
    assert os.stat(target).st_mode & 0o777 == 0o600
