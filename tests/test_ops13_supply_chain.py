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
    base = "https://github.com/fr0styx/zettnas-toolkit/.github/workflows/"
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
    jobs = yaml.safe_load(_read(".github/workflows/ci.yml"))["jobs"]
    steps = jobs["build-and-push"]["steps"]
    names = [s.get("name", "") for s in steps]
    build = next(s for s in steps if s.get("id") == "build")
    assert "push-by-digest=true" in build["with"]["outputs"] and "tags" not in build["with"]
    publish = next(i for i, n in enumerate(names) if n.startswith("Publish tags"))
    for gate in ("Smoke-test", "Scan image with Trivy", "Sign image digest"):
        assert next(i for i, n in enumerate(names) if n.startswith(gate)) < publish, gate
