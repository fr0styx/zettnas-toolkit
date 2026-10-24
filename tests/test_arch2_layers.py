"""Layering: core and service code never imports the API layer (ARCH-2)."""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent / "backend"
API_IMPORT = re.compile(r"^\s*(from backend\.api(\.|\s)|import backend\.api)", re.M)
ALLOWED = {"main.py"}  # the app wiring mounts the routers


def test_services_and_core_do_not_import_the_api():
    offenders = []
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if rel.parts[0] == "api" or str(rel) in ALLOWED:
            continue
        for m in API_IMPORT.finditer(path.read_text(encoding="utf-8")):
            line = path.read_text(encoding="utf-8")[: m.start()].count("\n") + 1
            offenders.append(f"backend/{rel}:{line}")
    assert offenders == [], "move the shared code out of backend/api: " + ", ".join(offenders)
