"""SET-07: "Save and recreate" never writes the dots of a hidden value into an app.

The Edit form was filled from details where secrets are dots. The server put a value back only
when it was exactly the dots, so "postgres://app:••••••••@db/app" went into the new container as
shown."""

import pytest

from backend.services import container_mutator
from backend.services.container_mutator import HIDDEN, _refuse_hidden_text

CURRENT = ["DB_PASSWORD=hunter2", "DATABASE_URL=postgres://app:hunter2@db/app", "TZ=Europe/Berlin"]


def test_a_whole_value_of_dots_is_put_back_as_before():
    _refuse_hidden_text([f"DB_PASSWORD={HIDDEN}", "TZ=Europe/Berlin"], CURRENT)  # no error
    payload = container_mutator._recreate_payload({}, {"Env": CURRENT}, [f"DB_PASSWORD={HIDDEN}"], {}, "img")
    assert "DB_PASSWORD=hunter2" in payload["Env"]


@pytest.mark.parametrize(
    "item, key",
    [
        (f"DATABASE_URL=postgres://app:{HIDDEN}@db/app", "DATABASE_URL"),
        (f"REDIS_URL=redis://:{HIDDEN}@cache:6379", "REDIS_URL"),
        (f"EXTRA_ARGS=--requirepass {HIDDEN} --appendonly yes", "EXTRA_ARGS"),
        (f"NEW_SECRET={HIDDEN}", "NEW_SECRET"),  # a new variable has nothing to be put back from
    ],
)
def test_dots_that_cannot_be_put_back_are_refused(item, key):
    with pytest.raises(ValueError) as e:
        _refuse_hidden_text([item, "TZ=Europe/Berlin"], CURRENT)
    assert key in str(e.value) and "Nothing was changed" in str(e.value)


def test_real_values_pass():
    _refuse_hidden_text(["DATABASE_URL=postgres://app:new-one@db/app", "TZ=UTC"], CURRENT)
    _refuse_hidden_text(None, CURRENT)


def test_the_recreate_stops_before_it_touches_the_app(monkeypatch):
    touched = []
    monkeypatch.setattr(
        container_mutator,
        "fetch_container_raw_inspect",
        lambda cid: {"Name": "/paperless", "Config": {"Env": CURRENT, "Image": "x"}, "HostConfig": {}},
    )
    for name in ("_docker_api_request", "docker_api_request", "_stop_container", "_rename_container"):
        if hasattr(container_mutator, name):
            monkeypatch.setattr(container_mutator, name, lambda *a, _n=name, **k: touched.append(_n))
    with pytest.raises(ValueError, match="DATABASE_URL still holds hidden text"):
        container_mutator.recreate_container("abc123", env=[f"DATABASE_URL=postgres://app:{HIDDEN}@db/app"])
    assert touched == []
