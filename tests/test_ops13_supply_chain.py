"""Signatures are accepted only from the release workflow; logs are capped (OPS-13)."""

import os
import re

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_promotion_verifies_the_ci_workflow_identity():
    text = _read(".github/workflows/promote.yml")
    m = re.search(r"--certificate-identity-regexp '([^']+)'", text)
    assert m, "promotion must verify a pinned identity"
    pattern = m.group(1).replace("${{ github.repository }}", "fr0styx/zettnas-toolkit")
    base = "https://github.com/fr0styx/kiboto/.github/workflows/"
    assert re.fullmatch(pattern, base + "ci.yml@refs/tags/v1.9.4")
    assert re.fullmatch(pattern, base + "ci.yml@refs/heads/main")
    assert not re.fullmatch(pattern, base + "other.yml@refs/heads/main")
    assert not re.fullmatch(pattern, base + "ci.yml@refs/heads/feature")


def test_linux_compose_caps_container_logs():
    services = yaml.safe_load(_read("docker-compose.linux.yml"))["services"]
    for name in ("zettnas-toolkit", "zettnas-samba"):
        opts = services[name]["logging"]["options"]
        assert opts["max-size"] and opts["max-file"], name


def test_images_get_tags_only_after_the_gates():
    # The image is built and checked in its own jobs while the tests run; the tags are added in
    # the publish job, which needs every check (CI speed-up, 12 Nov 2026)
    jobs = yaml.safe_load(_read(".github/workflows/ci.yml"))["jobs"]
    build = next(s for s in jobs["build-image"]["steps"] if s.get("id") == "build")
    assert "push-by-digest=true" in build["with"]["outputs"] and "tags" not in build["with"]
    names = [s.get("name", "") for s in jobs["publish"]["steps"]]
    publish = next(i for i, n in enumerate(names) if n.startswith("Publish tags"))
    assert next(i for i, n in enumerate(names) if n.startswith("Sign image digest")) < publish
    for gate, job in (
        ("Smoke-test", "check-image"),
        ("Smoke-test", "smoke-arm64"),
        ("Scan image with Trivy", "check-image"),
    ):
        assert any(s.get("name", "").startswith(gate) for s in jobs[job]["steps"]), (gate, job)
        assert job in jobs["publish"]["needs"], job


def test_arm64_images_are_started_in_ci():
    jobs = yaml.safe_load(_read(".github/workflows/ci.yml"))["jobs"]
    step = next(
        s for s in jobs["smoke-arm64"]["steps"] if s.get("name", "").startswith("Smoke-test the built image (arm64")
    )
    assert "smoke-arm64" in jobs["publish"]["needs"]
    assert "scripts/smoke_test.sh" in step["run"] and "linux/arm64" in step["run"]
    with open(os.path.join(ROOT, "scripts", "smoke_test.sh"), encoding="utf-8") as f:
        script = f.read()
    assert "--platform" in script and "aarch64" in script


def test_the_update_path_is_exercised_before_publishing():
    jobs = yaml.safe_load(_read(".github/workflows/ci.yml"))["jobs"]
    steps = jobs["update-test"]["steps"]
    names = [s.get("name", "") for s in steps]
    test = names.index("Upgrade and rollback test")
    assert "update-test" in jobs["publish"]["needs"]  # runs before any tag is published
    assert "scripts/upgrade_rollback_test.sh" in steps[test]["run"]
    assert os.path.isfile(os.path.join(ROOT, "scripts", "upgrade_rollback_test.sh"))
