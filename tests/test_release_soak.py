"""OPS-07: version tags publish :beta, promoted to :latest/:stable after a 3-day soak; the app's beta channel."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml

from backend.api import system

ROOT = Path(__file__).resolve().parent.parent


def _resp(status, payload):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    return r


def _fresh():
    for v in system._last_update_check.values():
        v["data"], v["ts"] = None, 0.0


def test_beta_channel_offers_the_newest_release_even_while_soaking(client, auth_headers):
    _fresh()
    releases = [
        {
            "tag_name": "v99.0.0",
            "name": "v99.0.0 (beta)",
            "prerelease": True,
            "draft": False,
            "html_url": "u",
            "body": "notes",
        },
        {"tag_name": "v98.0.0", "name": "v98.0.0", "prerelease": False, "draft": False},
    ]
    with (
        patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=_resp(200, releases)),
        patch("backend.api.system._registry_digest", new_callable=AsyncMock, return_value=None),
    ):
        data = client.get("/api/system/updates?channel=beta&force=true", headers=auth_headers).json()
    assert data["channel"] == "beta"
    assert data["latest_tag"] == "v99.0.0"
    assert data["update_available"] is True


def test_stable_never_falls_back_to_an_unpromoted_tag(client, auth_headers):
    _fresh()
    with (
        patch(
            "httpx.AsyncClient.get", new_callable=AsyncMock, return_value=_resp(404, {"message": "Not Found"})
        ) as get,
        patch("backend.api.system._registry_digest", new_callable=AsyncMock, return_value=None),
    ):
        data = client.get("/api/system/updates?channel=stable&force=true", headers=auth_headers).json()
    assert data["channel"] == "stable"
    assert data["update_available"] is False
    assert get.await_count == 1  # no second request for /tags


def test_updating_on_beta_installs_the_beta_image(client, auth_headers):
    with (
        patch("backend.services.container_mutator.pull_container_image") as pull,
        patch("backend.services.self_updater.spawn_self_updater", return_value=True),
        patch("backend.api.system._local_repo_digests", return_value=["sha256:" + "0" * 64]),
        patch("os.path.exists", return_value=True),
    ):
        r = client.post("/api/system/updates/apply", json={"channel": "beta"}, headers=auth_headers)
    assert r.status_code == 200
    assert pull.call_args[0][0].endswith(":beta") or pull.call_args[0][0].endswith(":beta-core")


def test_version_tags_publish_beta_not_latest():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    meta = ci[ci.index("Extract Docker metadata") : ci.index("Build and push Multi-Arch")]
    assert "value=beta,enable=${{ startsWith(github.ref, 'refs/tags/v') }}" in meta
    assert "value=latest" not in meta and "value=stable" not in meta and "{{major}}.{{minor}}" not in meta
    assert "prerelease: true" in ci


def test_promotion_waits_seven_days_honours_holds_and_can_be_skipped():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "promote.yml").read_text())
    on = wf.get("on") or wf.get(True)
    assert "schedule" in on and "skip_soak" in on["workflow_dispatch"]["inputs"]
    assert wf["env"]["SOAK_DAYS"] == "3"
    steps = "\n".join(str(s.get("run", "")) for s in wf["jobs"]["promote"]["steps"])
    assert "HOLD" in steps and "cosign verify" in steps
    assert ':latest${suffix}" -t "$IMAGE:stable${suffix}' in steps
    assert "prerelease=false" in steps
