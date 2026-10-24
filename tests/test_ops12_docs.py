"""Docs and the Unraid template describe the product as it is (OPS-12)."""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_readme_has_no_hard_coded_test_counts_or_in_image_test_runs():
    readme = _read("README.md")
    assert not re.search(r"\d+\+? (unit and integration )?tests", readme)
    assert "pytest -q /app/tests" not in readme


def test_unraid_template_describes_the_nas_desktop():
    xml = _read("unraid/zettnas-toolkit.xml")
    overview = re.search(r"<Overview>(.*?)</Overview>", xml, re.S).group(1)
    assert "web desktop" in overview and "backups" in overview


def test_update_channels_are_documented():
    guide = _read("docs/INSTALLATION.md")
    for channel in ("**Stable**", "**Beta**", "**Edge**"):
        assert channel in guide
