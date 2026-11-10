"""R1-1: names from before the Kiboto rebrand live in backend/legacy_names.py, or stay on purpose
(see its docstring). This ratchet fails when a file gains an old name; when one goes, lower its
count here (python tests/test_rebrand_ratchet.py prints the current counts)."""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
OLD = re.compile(r"zettnas|zetty|zettai", re.I)
# history and data that keep the old name: released changelog sections, the archive of old plans,
# the generated API snapshot (it follows the code), and the old Unraid templates (until 2.2)
SKIP = re.compile(
    r"^(CHANGELOG\.md|docs/archive/|docs/openapi-v1\.json|unraid/zettnas-|backend/legacy_names\.py$"
    r"|tests/test_rebrand_ratchet\.py$|tests/rebrand_baseline\.json$)"
)
BASELINE = ROOT / "tests" / "rebrand_baseline.json"


# the source the project ships (the test image has no git to list tracked files)
DIRS = (
    "backend",
    "frontend/src",
    "frontend/scripts",
    "scripts",
    "docs",
    "tests",
    ".github",
    "unraid",
    "tools",
    "contrib",
)
ROOT_FILES = re.compile(r"^[^/]+\.(md|yml|yaml|toml|json|txt)$|^Dockerfile$|^LICENSE$")
NOT_SOURCE = re.compile(r"(^|/)(__pycache__|node_modules|\.pytest_cache)(/|$)|\.pyc$")


def _files() -> list[str]:
    out = [p.name for p in ROOT.iterdir() if p.is_file() and ROOT_FILES.match(p.name)]
    out.append("frontend/index.html")
    for d in DIRS:
        out += [str(p.relative_to(ROOT)) for p in (ROOT / d).rglob("*") if p.is_file() and not p.is_symlink()]
    return sorted(f for f in out if not NOT_SOURCE.search(f) and f not in ("package-lock.json",))


def counts() -> dict[str, int]:
    out = {}
    for f in _files():
        if SKIP.match(f) or not (ROOT / f).is_file():
            continue
        try:
            text = (ROOT / f).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        n = len(OLD.findall(text))
        if n:
            out[f] = n
    return out


def test_old_names_do_not_spread():
    allowed = json.loads(BASELINE.read_text(encoding="utf-8"))
    grew = {f: (n, allowed.get(f, 0)) for f, n in counts().items() if n > allowed.get(f, 0)}
    assert not grew, (
        "Old product names (ZettNAS, Zetty, ZettAI) grew in: "
        + ", ".join(f"{f} ({n} > {a})" for f, (n, a) in sorted(grew.items()))
        + ". Use backend/product.py for the name, or backend/legacy_names.py for what must stay."
    )


if __name__ == "__main__":
    print(json.dumps(dict(sorted(counts().items())), indent=1))
