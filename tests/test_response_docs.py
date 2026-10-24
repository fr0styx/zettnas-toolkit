"""Documented response schemas for the API routes (ARCH-11)."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def test_most_api_operations_document_their_response():
    from backend.main import app

    doc = app.openapi()
    ops = [
        o for item in doc["paths"].values() for m, o in item.items() if m in ("get", "post", "put", "delete", "patch")
    ]

    def typed(op):
        for code, resp in op.get("responses", {}).items():
            schema = ((resp.get("content") or {}).get("application/json") or {}).get("schema")
            if code.startswith("2") and schema not in (None, {}):
                return True
        return False

    share = sum(map(typed, ops)) / len(ops)
    assert share >= 0.75, f"only {share:.0%} of operations document their response"


def test_every_documented_route_exists():
    from backend.api_docs import canonical_key, iter_routes
    from backend.models.responses import ROUTE_RESPONSES

    keys = {canonical_key(m, full) for full, r in iter_routes() for m in r.methods}
    assert not set(ROUTE_RESPONSES) - keys, "schemas for routes that are gone: regenerate"


def test_documentation_does_not_validate_responses():
    """Schemas are attached for the docs only: a route returning something new still works."""
    from backend.api_docs import iter_routes

    documented = [r for _, r in iter_routes() if r.response_model is None and r.responses]
    assert documented
    assert all(r.response_field is None for r in documented)


def test_document_responses_is_idempotent():
    from backend.api_docs import document_responses
    from backend.main import app

    assert document_responses(app) == 0  # already done at import


def test_routes_with_a_response_model_keep_it():
    from backend.api_docs import iter_routes

    jobs = [r for full, r in iter_routes() if full.endswith("/jobs") and "GET" in r.methods]
    assert jobs and jobs[0].response_model is not None


class TestGenerator:
    @pytest.fixture(autouse=True)
    def _g(self):
        import gen_response_models as g

        self.g = g

    def shape(self, *values):
        s = self.g.Shape()
        for v in values:
            s.add(v)
        return s

    def test_fields_are_nullable_and_typed(self):
        w = self.g.Writer()
        name = w.model(self.shape({"a": 1, "b": "x", "c": [1, 2]}, {"a": 2.5, "b": None}), "T")
        src = w.classes[-1]
        assert name == "T"
        assert "a: float | None = None" in src
        assert "b: str | None = None" in src
        assert "c: list[float] | None = None" in src

    def test_odd_keys_get_aliases(self):
        w = self.g.Writer()
        w.model(self.shape({"rx-bytes": 1, "json": "x", "class": True}), "T")
        src = w.classes[-1]
        assert 'alias="rx-bytes"' in src and 'alias="json"' in src and 'alias="class"' in src

    def test_data_keyed_objects_become_maps(self):
        s = self.shape({"1.3.6.1": {"value": "a"}, "1.3.6.2": {"value": 4}})
        assert self.g.map_like(s)
        ann = self.g.Writer().annotation(s, "Oids")
        assert ann.startswith("dict[str, ")

    def test_merge_keeps_every_value_type(self):
        a, b = self.shape({"v": "x"}), self.shape({"v": 3})
        merged = self.g.merge(a, b)
        assert merged.fields["v"].kinds == {"str", "int"}
