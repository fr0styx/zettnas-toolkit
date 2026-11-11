"""SET-07, the owner's decision S21: saving a stack never rewrites what the editor hid.

The editor loads the Compose file with dots where a line may hold a secret. On save each such
line was restored from the first line of the old file with the same key name, cut at the first
space or "#". A second service received the first one's image and password, and a command lost
everything after its first word. Hidden lines are now put back by their position, and a save
that cannot put one back is refused."""

import pytest

from backend.services import docker_stacks
from backend.services.docker_stacks import MASK, mask_compose_secrets, mask_env_secrets, unmask_by_position

COMPOSE = """services:
  cache:
    image: docker.io/valkey/valkey:8
    container_name: authentik-cache
    command: redis-server --requirepass s3cret-one --appendonly yes
  worker:
    image: ghcr.io/goauthentik/server:2026.2
    container_name: authentik-worker
    environment:
      - AUTHENTIK_SECRET_KEY=the-second-secret # do not share
      - AUTHENTIK_REDIS__HOST=cache
      - DATABASE_URL=postgres://app:pw@db/app
    ports:
      - "9000:9000"
"""
ENV = "POSTGRES_PASSWORD=hunter2 two\nTZ=Europe/Berlin\nAPI_TOKEN=abc#123\n"


def _save(new_compose, new_env=None, old_compose=COMPOSE, old_env=ENV):
    return docker_stacks._restore_masked_stack_secrets(new_compose, new_env, old_compose, old_env)


def test_an_untouched_file_comes_back_exactly():
    """Open, change nothing, save: every byte as it was. This is the case that did the damage."""
    compose, env = _save(mask_compose_secrets(COMPOSE), mask_env_secrets(ENV))
    assert compose == COMPOSE.rstrip("\n") and env == ENV.rstrip("\n")
    # what the old restore produced is not in it
    assert "command: redis-server --requirepass s3cret-one --appendonly yes" in compose
    assert compose.count("image: docker.io/valkey/valkey:8") == 1
    assert "image: ghcr.io/goauthentik/server:2026.2" in compose


def test_the_mask_hides_whole_values_and_keeps_the_line_count():
    masked = mask_compose_secrets(COMPOSE)
    assert len(masked.splitlines()) == len(COMPOSE.splitlines())
    for secret in ("s3cret-one", "the-second-secret", "pw@db"):
        assert secret not in masked
    assert masked.count(MASK) >= 4
    assert "hunter2" not in mask_env_secrets(ENV) and "TZ=Europe/Berlin" in mask_env_secrets(ENV)


def test_an_edit_elsewhere_keeps_every_hidden_line():
    masked = mask_compose_secrets(COMPOSE).replace('- "9000:9000"', '- "9443:9000"')
    masked = masked.replace("services:", "# my stack\nservices:")  # a line added above everything
    compose, _ = _save(masked)
    assert compose == COMPOSE.rstrip("\n").replace('- "9000:9000"', '- "9443:9000"').replace(
        "services:", "# my stack\nservices:"
    )


def test_a_removed_service_takes_its_hidden_lines_with_it():
    lines = mask_compose_secrets(COMPOSE).splitlines()
    without_cache = "\n".join(lines[:1] + lines[5:])
    compose, _ = _save(without_cache)
    assert "valkey" not in compose and "s3cret-one" not in compose
    assert "AUTHENTIK_SECRET_KEY=the-second-secret # do not share" in compose
    assert "image: ghcr.io/goauthentik/server:2026.2" in compose


def test_a_hidden_line_that_was_changed_is_refused_and_named():
    masked = mask_compose_secrets(COMPOSE).splitlines()
    at = next(i for i, line in enumerate(masked) if "AUTHENTIK_SECRET_KEY" in line)
    masked[at] = masked[at].replace("AUTHENTIK_SECRET_KEY", "AUTHENTIK_SECRET_KEY_NEW")
    with pytest.raises(ValueError) as e:
        _save("\n".join(masked))
    assert f"line {at + 1}" in str(e.value) and "Show secrets" in str(e.value) and "Nothing was saved" in str(e.value)


def test_a_new_line_with_dots_is_refused():
    masked = mask_compose_secrets(COMPOSE) + f"\n      - NEW_PASSWORD={MASK}"
    with pytest.raises(ValueError, match="cannot be put back"):
        _save(masked)
    with pytest.raises(ValueError, match="The .env file"):
        _save(mask_compose_secrets(COMPOSE), mask_env_secrets(ENV) + f"\nOTHER_KEY={MASK}")


def test_a_secret_typed_in_plain_is_saved_as_typed():
    masked = mask_compose_secrets(COMPOSE).splitlines()
    at = next(i for i, line in enumerate(masked) if "AUTHENTIK_SECRET_KEY" in line)
    masked[at] = "      - AUTHENTIK_SECRET_KEY=a brand new one"
    compose, env = _save("\n".join(masked), "POSTGRES_PASSWORD=changed\nTZ=Europe/Berlin\nAPI_TOKEN=" + MASK)
    assert "- AUTHENTIK_SECRET_KEY=a brand new one" in compose and "the-second-secret" not in compose
    assert "--requirepass s3cret-one --appendonly yes" in compose  # the other hidden lines are whole
    assert env == "POSTGRES_PASSWORD=changed\nTZ=Europe/Berlin\nAPI_TOKEN=abc#123"


def test_with_secrets_shown_the_text_is_saved_as_sent():
    edited = COMPOSE.replace("s3cret-one", "another")
    compose, env = _save(edited, ENV)
    assert compose == edited.rstrip("\n") and env == ENV.rstrip("\n")


def test_dots_that_someone_wrote_into_the_file_are_not_a_lost_secret():
    old = f"services:\n  app:\n    image: nginx\n    labels:\n      note: {MASK}\n"
    compose, _ = _save(mask_compose_secrets(old), None, old, "")
    assert compose == old.rstrip("\n")


def test_unmask_by_position_reports_the_lines():
    text, lost = unmask_by_position(f"a: 1\nkey: {MASK}\nextra_token: {MASK}", "a: 1\nkey: real", f"a: 1\nkey: {MASK}")
    assert text.splitlines()[:2] == ["a: 1", "key: real"] and lost == [3]


def test_the_save_refuses_and_writes_nothing(tmp_path, monkeypatch):
    target = tmp_path / "docker-compose.yml"
    target.write_text(COMPOSE)
    monkeypatch.setattr(
        docker_stacks,
        "get_stack_details",
        lambda name: {
            "compose_yaml": COMPOSE,
            "env_content": "",
            "location_type": "host_fs",
            "config_file": str(target),
            "working_dir": str(tmp_path),
        },
    )
    monkeypatch.setattr(docker_stacks, "stack_path_ok", lambda path, kind: True)
    bad = mask_compose_secrets(COMPOSE).replace("AUTHENTIK_SECRET_KEY", "AUTHENTIK_SECRET_KEY_NEW")
    res = docker_stacks.save_stack_config("authentik", bad, None)
    assert res["success"] is False and "Show secrets" in res["error"]
    assert target.read_text() == COMPOSE and list(tmp_path.glob("*.bak.*")) == []
    res = docker_stacks.save_stack_config("authentik", mask_compose_secrets(COMPOSE), None)
    assert res["success"] is True and target.read_text() == COMPOSE.rstrip("\n")


def test_the_route_says_whether_secrets_are_shown(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        docker_stacks,
        "get_stack_details",
        lambda name: {"compose_yaml": COMPOSE, "env_content": ENV, "has_real_file": True, "containers": []},
    )
    hidden = client.get("/api/docker/stacks/authentik", headers=auth_headers).json()
    assert hidden["secrets_shown"] is False and "s3cret-one" not in hidden["compose_yaml"]
    assert "hunter2" not in hidden["env_content"]
    shown = client.get("/api/docker/stacks/authentik?unmask=true", headers=auth_headers).json()
    assert shown["secrets_shown"] is True and shown["compose_yaml"] == COMPOSE and shown["env_content"] == ENV
