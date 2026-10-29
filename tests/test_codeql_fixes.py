"""Fixes for code scanning findings, each with the alert it answers."""

import json

from backend.hardware.net import tailscale, tailscale_setup


def test_only_real_sign_in_links_are_shown(monkeypatch):
    """CodeQL #382 (incomplete URL substring sanitization): any https link in tailscale's output
    used to become the sign-in link when the text mentioned login.tailscale.com."""
    monkeypatch.setattr(tailscale, "_get_tailscale_container_info", lambda: {"exists": False})
    monkeypatch.setattr(tailscale, "login_server", lambda: "")
    calls = []

    def fake(cmd, timeout=0):
        calls.append(cmd)
        if cmd[0] == "up":
            return 1, "To sign in, see login.tailscale.com or https://evil.example/a/123"
        return 0, json.dumps({"AuthURL": "https://evil.example/a/456"})

    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", fake)
    res = tailscale_setup.execute_tailscale_up()
    assert not res.get("auth_url")

    def real(cmd, timeout=0):
        if cmd[0] == "up":
            return 1, "To authenticate, visit:\n\n\thttps://login.tailscale.com/a/abc123\n"
        return 0, "{}"

    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", real)
    assert tailscale_setup.execute_tailscale_up()["auth_url"] == "https://login.tailscale.com/a/abc123"

    def status_only(cmd, timeout=0):
        if cmd[0] == "up":
            return 1, "waiting"
        return 0, json.dumps({"AuthURL": "https://login.tailscale.com/a/xyz"})

    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", status_only)
    assert tailscale_setup.execute_tailscale_up()["auth_url"] == "https://login.tailscale.com/a/xyz"


def test_snapshot_names_are_one_name(tmp_path):
    """py/path-injection: a snapshot or subvolume name like ../@shares/media used to reach
    btrfs as a path outside the snapshots folder (delete would then skip the WORM lock)."""
    import pytest

    from backend.fsutil import child_path, single_name

    for bad in ("", ".", "..", "../x", "a/b", "x\x00"):
        with pytest.raises(ValueError):
            single_name(bad)
        with pytest.raises(ValueError):
            child_path(str(tmp_path), bad)
    assert child_path(str(tmp_path), "media@2026-10-29") == str(tmp_path / "media@2026-10-29")


def test_snapshot_requests_refuse_paths(client, auth_headers):
    bad = client.post(
        "/api/backup/snapshots", headers=auth_headers, json={"subvol_name": "media", "snapshot_name": "../x"}
    )
    assert bad.status_code == 422
    bad = client.post(
        "/api/backup/restore-snapshot", headers=auth_headers, json={"snapshot_name": "s", "target_subvol": "../etc"}
    )
    assert bad.status_code == 422


def test_resolve_within_still_answers_the_same(tmp_path):
    from backend.fsutil import resolve_within

    (tmp_path / "a").mkdir()
    assert resolve_within(str(tmp_path), str(tmp_path)) == str(tmp_path.resolve())
    assert resolve_within(str(tmp_path / "a"), str(tmp_path)) == str((tmp_path / "a").resolve())
    assert resolve_within(str(tmp_path / ".." / "x"), str(tmp_path)) is None
    assert resolve_within(str(tmp_path) + "-other", str(tmp_path)) is None


def test_log_values_stay_on_one_line():
    """py/log-injection: a pool name with a line break could fake a log entry."""
    from backend.logging_config import one_line

    assert one_line("pool\n2026-10-29 - ZettNAS - INFO - fake\r") == "pool\\n2026-10-29 - ZettNAS - INFO - fake\\r"
    assert one_line(ValueError("x")) == "x"


def test_mfa_token_never_signed_with_a_built_in_key(monkeypatch):
    """The "password ok, now the code" token fell back to a key written in the source."""
    import base64
    import hashlib
    import hmac
    import time

    from backend import config
    from backend.api import auth as auth_api

    monkeypatch.setattr(config, "SECRET_KEY", "")
    tok = auth_api.create_mfa_token("1", "admin", False)
    assert auth_api.verify_mfa_token(tok)["u"] == "admin"
    raw = json.dumps({"uid": "1", "u": "admin", "rm": False, "exp": time.time() + 300}, separators=(",", ":"))
    b64 = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    forged = hmac.new(b"zettnas-mfa-default-key", b64.encode(), hashlib.sha256).hexdigest()
    assert auth_api.verify_mfa_token(f"mfa_{b64}.{forged}") is None


def test_hugging_face_ids_and_image_tags_are_checked():
    """py/partial-ssrf: only a real owner/name or image tag goes into the request URL."""
    import asyncio

    from backend.api import system
    from backend.services.media_engine import _normalize_hf_repo_input, is_hf_repo_id

    assert is_hf_repo_id("Qwen/Qwen3-4B") and is_hf_repo_id("org/model.v2_x-1")
    for bad in ("../../x", "org/../x", "org/.x", "a b/c", "org/model/extra", "org"):
        assert not is_hf_repo_id(bad), bad
    assert _normalize_hf_repo_input("https://huggingface.co/Qwen/Qwen3-4B/tree/main") == "Qwen/Qwen3-4B"
    assert asyncio.run(system._registry_digest("../../v2/other/manifests/x")) is None


def test_slow_regex_inputs_are_bounded():
    """py/polynomial-redos: long hostile strings come back quickly."""
    import time

    from backend.services import notifications
    from backend.services.media_engine import _normalize_hf_repo_input

    t0 = time.monotonic()
    _normalize_hf_repo_input("/tree/" * 50_000)
    try:
        notifications.set_route("nobody", email="a@" + "." * 50_000)
    except ValueError:
        pass
    assert time.monotonic() - t0 < 2


def test_script_tags_with_a_space_are_stripped():
    """py/bad-tag-filter: </script > is still the end of a script."""
    from backend.services.chat_web_tools import _strip_html_tags

    assert _strip_html_tags("<p>hi</p><script>evil()</script ><p>there</p>") == "hi there"


def test_phone_sign_in_page_escapes_what_it_shows(client):
    """py/reflective-xss: the provider and sign-in link are escaped in the phone page."""
    import time

    from backend.api import remotes

    remotes._ACTIVE_OAUTH_SESSIONS["sidx"] = {
        "provider_type": "<img src=x onerror=alert(1)>",
        "auth_url": 'https://login.example/a?x=1&y="><script>',
        "started_at": time.time(),
    }
    try:
        page = client.get("/api/remotes/oauth/mobile-page?sid=sidx").text
    finally:
        remotes._ACTIVE_OAUTH_SESSIONS.pop("sidx", None)
    assert "<img src=x" not in page and '"><script>' not in page
    assert "&lt;img src=x onerror=alert(1)&gt;" in page


def test_stack_env_files_are_private(tmp_path, monkeypatch):
    """py/clear-text-storage: a stack's .env holds its passwords; only root reads it now."""
    import os
    import stat

    from backend.services import docker_stacks

    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n")
    monkeypatch.setattr(
        docker_stacks,
        "get_stack_details",
        lambda name: {"location_type": "host_fs", "config_file": str(compose), "working_dir": str(tmp_path)},
    )
    monkeypatch.setattr(docker_stacks, "stack_path_ok", lambda *a: True)
    res = docker_stacks.save_stack_config("s", "services: {}\n", "DB_PASSWORD=x\n")
    assert res["success"], res
    assert stat.S_IMODE(os.stat(tmp_path / ".env").st_mode) == 0o600
    baks = [p for p in os.listdir(tmp_path) if ".bak." in p]
    assert baks and stat.S_IMODE(os.stat(tmp_path / baks[0]).st_mode) == 0o600
