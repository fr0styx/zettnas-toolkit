"""NARC-10: the test tools CI installs are hash-locked like the image's own packages, and the two
locks agree, so installing the tools can't change anything the image ships."""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", re.M)


def _pins(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        text = f.read()
    return {re.sub(r"[-_.]+", "-", m.group(1)).lower(): m.group(2) for m in PIN.finditer(text)}, text


def test_every_dev_pin_is_hashed():
    _, text = _pins("requirements-dev.lock")
    blocks = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", text.split("\n", 7)[-1])
    for block in blocks:
        if PIN.match(block):
            assert "--hash=sha256:" in block, block.splitlines()[0]


def test_the_dev_lock_keeps_the_image_packages_as_they_are():
    image, _ = _pins("requirements.lock")
    dev, _ = _pins("requirements-dev.lock")
    changed = {k: (v, dev.get(k)) for k, v in image.items() if dev.get(k) not in (None, v)}
    assert not changed, f"the dev lock moves image packages: {changed}"


def test_the_tools_are_locked_at_the_versions_asked_for():
    asked, _ = _pins("requirements-dev.txt")
    dev, _ = _pins("requirements-dev.lock")
    assert asked and all(dev.get(k) == v for k, v in asked.items()), {k: (v, dev.get(k)) for k, v in asked.items()}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def test_the_image_build_sees_every_file_the_dockerfile_copies():
    """.dockerignore lets only listed files into the build: a file COPY names but the list leaves
    out fails the image build, not the tests (the dev lock did, in 9f73bb8)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    allowed = {
        line[1:].strip().rstrip("/") for line in _read(os.path.join(root, ".dockerignore")) if line.startswith("!")
    }
    for line in _read(os.path.join(root, "Dockerfile")):
        if not line.startswith("COPY ") or "--from=" in line:
            continue
        sources = [s for s in line.split()[1:-1] if not s.startswith("--")]
        for src in sources:
            top = src.strip("./").split("/")[0]
            if top:
                inside = any(a.startswith(top + "/") for a in allowed)  # static/: some files of it
                assert top in allowed or inside, f"{src} is copied but .dockerignore leaves it out"
