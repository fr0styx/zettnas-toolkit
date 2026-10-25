"""UX-9: nothing a person reads is smaller than 13px (the LCD and its scaled previews excepted)."""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_no_text_below_13px():
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "type_min.py"), "--dry"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.startswith("0 sizes raised"), "text below 13px; run python scripts/type_min.py:\n" + out
