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


def test_smoke_script_runs_each_platform_by_its_own_manifest():
    """Running a second platform of an already pulled digest fails ("cannot overwrite digest")."""
    root = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(root, "scripts", "smoke_test.sh"), encoding="utf-8") as f:
        script = f.read()
    assert "imagetools inspect --raw" in script and 'ref="$repo@$platform_digest"' in script


def test_published_images_can_be_smoke_tested_on_demand():
    root = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(root, ".github", "workflows", "smoke.yml"), encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    run = wf["jobs"]["smoke"]["steps"][-1]["run"]
    assert "scripts/smoke_test.sh" in run
    assert "${{" not in run  # inputs reach the script through env, never pasted into the shell
