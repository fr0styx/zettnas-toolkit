"""CSS per lazy window (ARC-12): a sheet that loads with a window must keep its cascade order.

Lazily loaded CSS lands after every global sheet. A sheet that used to sit at position NN
therefore only changes order against the global sheets numbered after it; when none of
those has a rule of the same specificity for the same properties on the same classes, the
move changes nothing.
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STYLES = os.path.join(ROOT, "frontend", "src", "styles")
GLOBAL = os.path.join(ROOT, "frontend", "src", "style.css")
COMPONENTS = os.path.join(ROOT, "frontend", "src", "components")
# each lazy sheet, and the modules that load it (the first one to load brings it)
LAZY = {
    "management-lazy.css": [os.path.join(COMPONENTS, "management.js")],
    "vm-lazy.css": [os.path.join(COMPONENTS, "vm-manager.js")],
    "files-lazy.css": [os.path.join(COMPONENTS, "file-manager.js"), os.path.join(COMPONENTS, "file-preview-modal.js")],
    "viewer-lazy.css": [os.path.join(COMPONENTS, "file-preview-modal.js")],
}
# state classes shared by unrelated components; a rule pair must share another class to collide
GENERIC = {"active", "open", "show", "visible", "hidden", "collapsed", "disabled", "danger", "ok", "warn", "crit"}


def imports(path):
    with open(path, encoding="utf-8") as f:
        return re.findall(r"@import '\./(?:styles/)?([\w.-]+\.css)'", f.read())


def rules(name):
    with open(os.path.join(STYLES, name), encoding="utf-8") as f:
        text = re.sub(r"/\*.*?\*/", "", f.read(), flags=re.S)
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        sel = m.group(1).strip()
        if sel.startswith("@") or re.match(r"^(from|to|\d+%)\b", sel):
            continue
        props = {p.split(":")[0].strip() for p in m.group(2).split(";") if ":" in p}
        out += [(s.strip(), props) for s in sel.split(",") if s.strip()]
    return out


def specificity(sel):
    s = re.sub(r":(not|is|has)\(([^()]*)\)", r" \2", re.sub(r":where\([^()]*\)", "", sel))
    ids = len(re.findall(r"#[\w-]+", s))
    classes = len(re.findall(r"\.[\w-]+|\[[^\]]+\]|:(?!:)[\w-]+", s))
    elements = len(re.findall(r"(?:^|[\s>+~])[a-zA-Z][\w-]*", s)) + len(re.findall(r"::[\w-]+", s))
    return ids, classes, elements


def target_classes(sel):
    last = re.split(r"[\s>+~]+", sel.strip())[-1]
    return set(re.findall(r"[.#]([A-Za-z_][\w-]*)", last)) - GENERIC


def collisions(moved, later):
    found = []
    for s1, p1 in rules(moved):
        t1 = target_classes(s1)
        for s2, p2 in rules(later):
            if t1 & target_classes(s2) and specificity(s1) == specificity(s2) and p1 & p2:
                found.append(f"{moved} `{s1}` vs {later} `{s2}` on {sorted(p1 & p2)}")
    return found


def test_lazy_sheets_are_not_also_global():
    global_sheets = set(imports(GLOBAL))
    for lazy, modules in LAZY.items():
        assert lazy not in global_sheets
        for sheet in imports(os.path.join(STYLES, lazy)):
            assert sheet not in global_sheets, f"{sheet} is loaded both globally and with a window"
        for module in modules:
            with open(module, encoding="utf-8") as f:
                assert f"styles/{lazy}'" in f.read(), f"{os.path.basename(module)} must import {lazy}"


def test_moved_sheets_keep_their_cascade_order():
    global_sheets = imports(GLOBAL)
    problems = []
    for lazy in LAZY:
        for sheet in imports(os.path.join(STYLES, lazy)):
            number = int(sheet.split("-", 1)[0])
            for later in global_sheets:
                if int(later.split("-", 1)[0]) > number:
                    problems += collisions(sheet, later)
    assert not problems, "these rules would change order if loaded lazily:\n" + "\n".join(problems[:10])


def test_the_collision_check_catches_a_real_one(tmp_path, monkeypatch):
    (tmp_path / "10-a.css").write_text(".x .card { color: red; }")
    (tmp_path / "20-b.css").write_text(".y .card { color: blue; } .card.active.big { color: green; }")
    monkeypatch.setitem(globals(), "STYLES", str(tmp_path))
    assert collisions("10-a.css", "20-b.css") == ["10-a.css `.x .card` vs 20-b.css `.y .card` on ['color']"]
    (tmp_path / "30-c.css").write_text(".net-btn.active { color: red; }")
    (tmp_path / "40-d.css").write_text(".wall-pill.active { color: red; }")
    assert collisions("30-c.css", "40-d.css") == []  # only the state class in common
