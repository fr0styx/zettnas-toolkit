"""ARCH-11: shared paging and response models on the new routes."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.paging import PageParams

app = FastAPI()


@app.get("/things")
def things(page: PageParams = Depends()):
    rows = list(range(page.fetch))[:23]  # a source with 23 rows
    return {"things": page.slice(rows), **page.meta(len(rows))}


@pytest.mark.parametrize(
    "query,items,next_offset",
    [("", list(range(23)), None), ("?limit=10", list(range(10)), 10), ("?limit=10&offset=20", [20, 21, 22], None)],
)
def test_pages(query, items, next_offset):
    r = TestClient(app).get("/things" + query).json()
    assert r["things"] == items and r["next_offset"] == next_offset


def test_limits_are_validated():
    c = TestClient(app)
    assert c.get("/things?limit=0").status_code == 422
    assert c.get("/things?limit=100000").status_code == 422
    assert c.get("/things?offset=-1").status_code == 422


def test_new_routes_publish_their_response_shape():
    from backend.main import app as real

    spec = real.openapi()
    for path in ("/api/v1/jobs", "/api/v1/setup/checklist", "/api/v1/metrics/requests"):
        op = spec["paths"][path]["get"]
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert "$ref" in schema, path
