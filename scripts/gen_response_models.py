"""Generates backend/models/responses.py: documented response schemas for every API route (ARCH-11).

The schemas come from what the routes really return. The test suite records each JSON
response (tests/conftest.py, ZETTNAS_RECORD_RESPONSES); routes no test reaches are read
from the dictionary literals they return. Models accept extra fields. A route's top-level
field is required when every recorded response had it (seen at least twice, never null);
everything else is optional and nullable (ARC-7). The schemas are attached to the OpenAPI
documentation only (backend/api_docs.py), and the test suite checks every response it sees
against its schema (tests/response_contract.py), so a required field that goes missing
fails a test instead of breaking an API client.

    docker compose -f docker-compose.dev.yml --profile test run --rm -v /tmp/rec:/rec \\
        -e ZETTNAS_RECORD_RESPONSES=/rec/responses.jsonl zettnas-test tests
    docker compose -f docker-compose.dev.yml --profile test run --rm -v /tmp/rec:/rec \\
        -v $PWD:/out --entrypoint python zettnas-test scripts/gen_response_models.py \\
        /rec/responses.jsonl /out/backend/models/responses.py
"""

from __future__ import annotations

import ast
import inspect
import json
import keyword
import os
import re
import sys
import textwrap
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TESTING", "1")

from pydantic import BaseModel  # noqa: E402

from backend.api_docs import canonical_key, iter_routes  # noqa: E402

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RESERVED = set(dir(BaseModel)) | {"model_config", "Any", "Field", "BaseModel", "ConfigDict"}
NON_JSON_RETURNS = {
    "FileResponse",
    "StreamingResponse",
    "RedirectResponse",
    "HTMLResponse",
    "PlainTextResponse",
    "Response",
    "EventSourceResponse",
    "ServerSentEvent",
    "JSONResponse",
}


@dataclass
class Shape:
    kinds: set[str] = field(default_factory=set)
    fields: dict[str, Shape] = field(default_factory=dict)
    present: dict[str, int] = field(default_factory=dict)
    objects: int = 0
    items: Shape | None = None
    loose: bool = False  # from source: field types unknown

    def add(self, v) -> None:
        if v is None:
            self.kinds.add("null")
        elif isinstance(v, bool):
            self.kinds.add("bool")
        elif isinstance(v, int):
            self.kinds.add("int")
        elif isinstance(v, float):
            self.kinds.add("float")
        elif isinstance(v, str):
            self.kinds.add("str")
        elif isinstance(v, list):
            self.kinds.add("list")
            self.items = self.items or Shape()
            for item in v[:200]:
                self.items.add(item)
        elif isinstance(v, dict):
            self.kinds.add("object")
            self.objects += 1
            for k, sub in v.items():
                self.fields.setdefault(k, Shape()).add(sub)
                self.present[k] = self.present.get(k, 0) + 1


def merge(into: Shape, other: Shape) -> Shape:
    """Combines two shapes (the values of a data-keyed map, or helper returns)."""
    into.kinds |= other.kinds
    into.objects += other.objects
    into.loose = into.loose or other.loose
    for k, v in other.fields.items():
        merge(into.fields.setdefault(k, Shape()), v)
        into.present[k] = into.present.get(k, 0) + other.present.get(k, 0)
    if other.items is not None:
        into.items = merge(into.items or Shape(), other.items)
    return into


def map_like(s: Shape) -> bool:
    """An object keyed by data (device names, paths, ids) rather than by field names."""
    if not s.fields:
        return False
    keys = list(s.fields)
    data_keys = sum(1 for k in keys if not IDENT.match(k) or k[:1].isdigit())
    if data_keys and data_keys >= len(keys) / 2:
        return True
    return len(keys) > 24 and s.objects > 1 and max(s.present.values()) < s.objects


def camel(text: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", text)
    out = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return out if out[:1].isalpha() else "F" + out


class Writer:
    def __init__(self) -> None:
        self.classes: list[str] = []
        self.names: set[str] = set()

    def unique(self, name: str) -> str:
        base, n = name, 2
        while name in self.names:
            name = f"{base}{n}"
            n += 1
        self.names.add(name)
        return name

    @staticmethod
    def required(s: Shape, key: str, route_level: bool) -> bool:
        """A route's own field that every recorded response had (ARC-7)."""
        sub = s.fields[key]
        return (
            route_level
            and not s.loose
            and s.objects >= 2
            and s.present.get(key, 0) == s.objects
            and "null" not in sub.kinds
            and bool(sub.kinds)
        )

    def annotation(self, s: Shape | None, name: str) -> str:
        if s is None or s.loose and not s.kinds:
            return "Any"
        parts: list[str] = []
        if "object" in s.kinds:
            if map_like(s):
                values = Shape()
                for sub in s.fields.values():
                    merge(values, sub)
                # values keyed by data (OIDs, devices) vary in type between readings: any scalar
                if values.kinds & {"str", "int", "float", "bool"}:
                    values.kinds |= {"str", "int", "bool"}
                parts.append(f"dict[str, {self.annotation(values, name + 'Item')}]")
            else:
                parts.append(self.model(s, name))
        if "list" in s.kinds:
            parts.append(
                f"list[{self.annotation(s.items, name + 'Item')}]" if s.items and s.items.kinds else "list[Any]"
            )
        if "str" in s.kinds:
            parts.append("str")
        if "float" in s.kinds or "int" in s.kinds:
            parts.append("float")  # accepts ints too
        if "bool" in s.kinds:
            parts.append("bool")
        if not parts:
            return "Any"
        return " | ".join(dict.fromkeys(parts))

    def model(self, s: Shape, name: str, doc: str = "", route_level: bool = False) -> str:
        cls = self.unique(camel(name))
        lines = [f"class {cls}(_Doc):"]
        if doc:
            lines.append(f'    """{doc}"""')
            lines.append("")
        if not s.fields:
            lines.append("    pass")
        for key in sorted(s.fields):
            sub = s.fields[key]
            ann = self.annotation(sub, cls + camel(key))
            attr = key
            if not IDENT.match(key) or keyword.iskeyword(key) or key in RESERVED or key.startswith("_"):
                attr = "f_" + re.sub(r"\W", "_", key).strip("_") or "field"
                while attr in s.fields:
                    attr += "_"
                if self.required(s, key, route_level):
                    lines.append(f"    {attr}: {ann} = Field(..., alias={json.dumps(key)})")
                else:
                    lines.append(f"    {attr}: {ann} | None = Field(None, alias={json.dumps(key)})")
            elif self.required(s, key, route_level):
                lines.append(f"    {attr}: {ann}")
            else:
                lines.append(f"    {attr}: {ann} | None = None")
        self.classes.append("\n".join(lines))
        return cls


def _callee(value, func):
    """The function a return statement calls (return f(...), await f(...), asyncio.to_thread(f, ...))."""
    if isinstance(value, ast.Await):
        value = value.value
    if not isinstance(value, ast.Call):
        return None
    target = value.func
    if isinstance(target, ast.Attribute) and target.attr == "to_thread" and value.args:
        target = value.args[0]
    g = getattr(func, "__globals__", {})
    if isinstance(target, ast.Name):
        obj = g.get(target.id)
    elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
        obj = getattr(g.get(target.value.id), target.attr, None)
    else:
        return None
    return obj if inspect.isfunction(obj) else None


def shape_from_source(func, depth: int = 0) -> Shape | None | str:
    """Keys of the dictionary literals a route returns ("skip" for non-JSON responses)."""
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    except (OSError, TypeError, SyntaxError):
        return None
    fn = tree.body[0]
    assigned: dict[str, ast.AST] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            assigned[node.targets[0].id] = node.value
    returns = [n.value for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
    if not returns:
        return None
    shape = Shape(loose=True)
    found = False
    for value in returns:
        if isinstance(value, ast.Name) and value.id in assigned:
            value = assigned[value.id]
        if isinstance(value, ast.Call):
            callee = value.func.attr if isinstance(value.func, ast.Attribute) else getattr(value.func, "id", "")
            if callee in NON_JSON_RETURNS:
                return "skip"
        helper = _callee(value, func) if depth < 2 else None
        if helper is not None:
            sub = shape_from_source(helper, depth + 1)
            if sub == "skip":
                return "skip"
            if isinstance(sub, Shape):
                found = True
                merge(shape, sub)
                continue
        if isinstance(value, ast.Dict):
            found = True
            shape.kinds.add("object")
            shape.objects += 1
            for k, v in zip(value.keys, value.values, strict=False):
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    sub = shape.fields.setdefault(k.value, Shape(loose=True))
                    shape.present[k.value] = shape.present.get(k.value, 0) + 1
                    if isinstance(v, ast.Constant):
                        sub.add(v.value)
                    elif isinstance(v, (ast.List, ast.ListComp)):
                        sub.kinds.add("list")
                    elif isinstance(v, ast.Dict):
                        sub.kinds.add("object")
        elif isinstance(value, (ast.List, ast.ListComp)):
            found = True
            shape.kinds.add("list")
    return shape if found else None


def main(samples_path: str, out_path: str) -> None:
    routes = list(iter_routes())
    compiled = []
    from starlette.routing import compile_path

    for full, route in routes:
        compiled.append((compile_path(full)[0], full, route))
    shapes: dict[str, Shape] = {}
    funcs: dict[str, object] = {}
    for full, route in routes:
        if route.response_model is not None:
            continue
        for method in sorted(route.methods - {"HEAD"}):
            key = canonical_key(method, full)
            if key and "{unmatched_path" not in key:  # the 404 catch-all
                funcs.setdefault(key, route.endpoint)
    with open(samples_path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            for regex, full, route in compiled:
                if rec["method"] in route.methods and regex.match(rec["path"]):
                    key = canonical_key(rec["method"], full)
                    if key in funcs:
                        shapes.setdefault(key, Shape()).add(rec["body"])
                    break
    w = Writer()
    registry: list[tuple[str, str]] = []
    stats = {"recorded": 0, "source": 0, "skipped": 0, "unknown": 0}
    for key in sorted(funcs):
        func = funcs[key]
        shape = shapes.get(key)
        origin = "recorded"
        if shape is None:
            shape = shape_from_source(func)
            origin = "source"
            if shape == "skip":
                stats["skipped"] += 1
                continue
            if shape is None:
                stats["unknown"] += 1
                continue
        stats[origin] += 1
        name = camel(getattr(func, "__name__", "route")) + "Response"
        method, path = key.split(" ", 1)
        if shape.kinds == {"object"} and not map_like(shape):
            ann = w.model(shape, name, doc=f"{method} {path}", route_level=origin == "recorded")
        else:
            ann = w.annotation(shape, name)
        registry.append((key, ann))
    header = f'''"""Response schemas of the API routes, for the OpenAPI documentation (ARCH-11).

Generated by scripts/gen_response_models.py from responses recorded by the test suite
({stats["recorded"]} routes) and from the dictionaries routes return ({stats["source"]} routes); do not edit.
Fields every recorded response had are required; the rest are nullable, and extra fields
are allowed (ARC-7). tests/response_contract.py checks the responses the tests see against them.
"""

# ruff: noqa: E501

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Doc(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, protected_namespaces=())

'''
    body = "\n\n\n".join(w.classes)
    reg = "\n".join(f"    {json.dumps(k)}: {a}," for k, a in registry)
    footer = (
        '\n\n\n# Route ("METHOD /path" under /api/v1) -> its response schema\nROUTE_RESPONSES: dict[str, Any] = {\n'
    )
    text = header + "\n" + body + footer + reg + "\n}\n"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"{len(registry)} routes documented ({stats}); {len(w.classes)} models -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
