"""The release gates in CI block a bad image before any tag points at it (OPS-9, OPS-10)."""

import os

import yaml

CI = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".github", "workflows", "ci.yml")


def _jobs():
    with open(CI, encoding="utf-8") as f:
        return yaml.safe_load(f)["jobs"]


def _steps(job="publish"):
    return _jobs()[job]["steps"]


def _index(steps, prefix):
    return next(i for i, s in enumerate(steps) if s.get("name", "").startswith(prefix))


# Each release gate and the job that runs it (the image is built and checked while the tests
# run; CI speed-up, 12 Nov 2026)
GATES = {
    "Smoke-test the built image (amd64": "check-image",
    "Smoke-test the built image (arm64": "smoke-arm64",
    "Scan image with Trivy": "check-image",
    "Upgrade and rollback test": "update-test",
}


def test_arm64_smoke_and_upgrade_tests_are_blocking():
    jobs = _jobs()
    for prefix in ("Smoke-test the built image (arm64", "Upgrade and rollback test"):
        job = jobs[GATES[prefix]]
        step = job["steps"][_index(job["steps"], prefix)]
        assert not step.get("continue-on-error"), prefix
        assert not job.get("continue-on-error"), prefix


def test_every_gate_runs_before_the_image_is_signed_and_tagged():
    jobs = _jobs()
    steps = jobs["publish"]["steps"]
    assert _index(steps, "Sign image digest") < _index(steps, "Publish tags")
    needs = set(jobs["publish"]["needs"])
    # every test job and every image check must pass before anything is signed or tagged
    assert {"lint", "lint-and-test", "frontend", "e2e-integration", "still-latest", "build-image"} <= needs
    assert "lint" in jobs["still-latest"]["needs"]
    # the idle minute (PERF-10) is still one of the browser-test jobs
    e2e = jobs["e2e-integration"]["strategy"]["matrix"]["include"]
    assert any(e["idle"] is True for e in e2e) and all(e["tests"] for e in e2e if not e["idle"])
    for prefix, job in GATES.items():
        assert job in needs, prefix
        _index(jobs[job]["steps"], prefix)  # the gate is really in that job
        assert not jobs[job].get("if"), job  # and is not skipped while the build runs
    # nothing before the publish job tags or signs the image
    for name, job in jobs.items():
        if name in ("publish", "create-release"):
            continue
        for s in job.get("steps", []):
            run = str(s.get("run", ""))
            assert "cosign sign" not in run and "imagetools create" not in run, (name, s.get("name"))
    assert jobs["create-release"]["needs"] == ["publish"]


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


def test_changed_backend_lines_must_be_tested():
    """Diff coverage: new code cannot hide behind the overall percentage."""
    root = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(root, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
        job = yaml.safe_load(f)["jobs"]["lint-and-test"]
    run = "\n".join(s.get("run", "") for s in job["steps"])
    assert "diff-cover coverage.xml" in run and "--fail-under=80" in run
    assert job["steps"][0]["with"]["fetch-depth"] == 0
    with open(os.path.join(root, "requirements-dev.txt"), encoding="utf-8") as f:
        assert "diff-cover==" in f.read()
