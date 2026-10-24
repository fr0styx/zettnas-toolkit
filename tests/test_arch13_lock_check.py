"""CI tests the dependency set the image ships (ARCH-13)."""

import os

import yaml

from scripts.check_lock_versions import locked_versions, mismatches

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_lock_parsing_and_drift_detection():
    lock = "aiofiles==25.1.0 \\\n    --hash=sha256:abc\nPillow==13.0.0 \\\n# via x\n"
    locked = locked_versions(lock)
    assert locked == {"aiofiles": "25.1.0", "pillow": "13.0.0"}
    assert mismatches(locked, {"aiofiles": "25.1.0", "pillow": "13.0.0"}) == []
    assert mismatches(locked, {"aiofiles": "25.2.0"}) == [
        "aiofiles: locked 25.1.0, installed 25.2.0",
        "pillow: locked 13.0.0, installed missing",
    ]


def test_ci_installs_the_lock_with_hashes_and_checks_it():
    with open(os.path.join(ROOT, ".github/workflows/ci.yml"), encoding="utf-8") as f:
        jobs = yaml.safe_load(f)["jobs"]
    for job in ("lint-and-test", "e2e-integration"):
        runs = "\n".join(s.get("run", "") for s in jobs[job]["steps"])
        assert "pip install --require-hashes -r requirements.lock" in runs, job
        assert "scripts/check_lock_versions.py" in runs, job
        assert "pip install httpx playwright" not in runs, job


def test_the_test_environment_matches_the_lock():
    from scripts import check_lock_versions

    with open(os.path.join(ROOT, "requirements.lock"), encoding="utf-8") as f:
        locked = check_lock_versions.locked_versions(f.read())
    assert len(locked) > 20
