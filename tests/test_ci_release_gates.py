"""The release gates in CI block a bad image before any tag points at it (OPS-9, OPS-10)."""

import os

import yaml

CI = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".github", "workflows", "ci.yml")


def _steps():
    with open(CI, encoding="utf-8") as f:
        return yaml.safe_load(f)["jobs"]["build-and-push"]["steps"]


def _index(steps, prefix):
    return next(i for i, s in enumerate(steps) if s.get("name", "").startswith(prefix))


def test_arm64_smoke_and_upgrade_tests_are_blocking():
    steps = _steps()
    for prefix in ("Smoke-test the built image (arm64", "Upgrade and rollback test"):
        step = steps[_index(steps, prefix)]
        assert not step.get("continue-on-error"), prefix


def test_every_gate_runs_before_the_image_is_signed_and_tagged():
    steps = _steps()
    publish = _index(steps, "Publish tags")
    sign = _index(steps, "Sign image digest")
    for prefix in (
        "Smoke-test the built image (amd64",
        "Smoke-test the built image (arm64",
        "Scan image with Trivy",
        "Upgrade and rollback test",
    ):
        assert _index(steps, prefix) < sign < publish, prefix
