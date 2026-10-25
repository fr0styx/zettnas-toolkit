"""Built-in catalog apps install pinned by digest; updates still follow the tag and re-pin."""

import json

import pytest

from backend.services import docker_updates, image_ref

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64
FOLLOW = {image_ref.FOLLOW_TAG_LABEL: "1"}


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("nginx", ("docker.io", "library/nginx", "latest", "")),
        ("nginx:stable-alpine", ("docker.io", "library/nginx", "stable-alpine", "")),
        ("ghcr.io/org/app:2", ("ghcr.io", "org/app", "2", "")),
        ("reg.local:5000/team/app", ("reg.local:5000", "team/app", "latest", "")),
        ("reg.local:5000/team/app:1.2@" + A, ("reg.local:5000", "team/app", "1.2", A)),
        ("jellyfin/jellyfin@" + A, ("docker.io", "jellyfin/jellyfin", "latest", A)),
        ("index.docker.io/library/redis:7", ("docker.io", "library/redis", "7", "")),
    ],
)
def test_image_references_are_split(ref, expected):
    assert image_ref.split_ref(ref) == expected


def test_pull_parameters_handle_ports_and_digests():
    assert image_ref.pull_params("reg.local:5000/app") == ("reg.local:5000/app", "latest")
    assert image_ref.pull_params("nginx:1@" + A) == ("nginx", A)
    assert image_ref.pull_params("ghcr.io/org/app:2") == ("ghcr.io/org/app", "2")
    assert docker_updates.extract_registry_from_image("nginx:1@" + A) == ("docker.io", "library/nginx", "1")


@pytest.fixture
def lock(tmp_path, monkeypatch):
    path = tmp_path / "digests.json"
    path.write_text(json.dumps({"jellyfin/jellyfin:latest": A, "postgres:17": B, "broken:1": "nope"}))
    monkeypatch.setattr(image_ref, "_LOCK", str(path))
    image_ref._lock.cache_clear()
    yield
    image_ref._lock.cache_clear()


def test_built_in_apps_install_the_pinned_image(lock):
    app = {
        "image": "jellyfin/jellyfin:latest",
        "stack_services": {"db": {"image": "postgres:17"}, "x": {"image": "broken:1"}},
    }
    out = image_ref.pin_app(app)
    assert out["image"] == "jellyfin/jellyfin:latest@" + A
    assert out["stack_services"]["db"]["image"] == "postgres:17@" + B
    assert out["stack_services"]["x"]["image"] == "broken:1"  # an invalid entry is ignored
    assert app["image"] == "jellyfin/jellyfin:latest"  # the catalog itself is untouched


def test_only_the_built_in_catalog_is_pinned(lock, monkeypatch):
    from backend.services import app_catalog

    monkeypatch.setattr(
        app_catalog,
        "get_all_catalog_apps",
        lambda: [
            {"id": "jellyfin", "image": "jellyfin/jellyfin:latest", "source_id": "builtin"},
            {"id": "other", "image": "jellyfin/jellyfin:latest", "source_id": "portainer"},
        ],
    )
    assert app_catalog.get_catalog_app("jellyfin")["image"].endswith("@" + A)
    assert app_catalog.get_catalog_app("other")["image"] == "jellyfin/jellyfin:latest"


def test_the_shipped_catalog_is_pinned():
    """Every lock entry is a real digest, and nearly every catalog image has one."""
    import os

    from backend.services.catalog_templates import CURATED_APP_CATALOG

    images = set()
    for app in CURATED_APP_CATALOG:
        images.add(app.get("image"))
        images.update(s.get("image") for s in (app.get("stack_services") or {}).values() if isinstance(s, dict))
    images.discard(None)
    with open(os.path.join(os.path.dirname(image_ref.__file__), "catalog_digests.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert all(image_ref.DIGEST_RE.match(v) for v in data.values())
    assert len(images & set(data)) >= 0.9 * len(images), "run scripts/pin_catalog_images.py --missing"


def _fake_docker(remote, repo_digests):
    def fake(method, path, **kw):
        if path.startswith("/distribution/"):
            return 200, {"Descriptor": {"digest": remote}}
        if path.startswith("/images/"):
            return 200, {"RepoDigests": repo_digests}
        return 404, {}

    return fake


@pytest.mark.parametrize("remote, has_update", [(B, True), (A, False)])
def test_a_pinned_app_is_checked_against_its_tag(monkeypatch, remote, has_update):
    monkeypatch.setattr(docker_updates, "get_container_update_policy", lambda n: "notify")
    monkeypatch.setattr(docker_updates, "get_registry_auth_header", lambda i: {})
    paths = []
    fake = _fake_docker(remote, [])
    monkeypatch.setattr(docker_updates, "_docker_request", lambda m, p, **kw: paths.append(p) or fake(m, p, **kw))
    res = docker_updates._check_container_image_update(
        {"Names": ["/jf"], "Id": "x" * 12, "Image": "jellyfin/jellyfin:latest@" + A, "Labels": FOLLOW}
    )
    assert res["has_update"] is has_update and res["local_digest"] == A
    assert paths[0] == "/distribution/jellyfin/jellyfin:latest/json"


def test_a_digest_without_a_tag_stays_pinned(monkeypatch):
    monkeypatch.setattr(docker_updates, "get_container_update_policy", lambda n: "notify")
    res = docker_updates._check_container_image_update(
        {"Names": ["/jf"], "Id": "x", "Image": "jellyfin/jellyfin@" + A, "Labels": FOLLOW}
    )
    assert res["status"] == "pinned"
    # a digest its owner pinned (no ZettNAS label) is left alone, tag or not
    res = docker_updates._check_container_image_update({"Names": ["/v"], "Id": "x", "Image": "valkey/valkey:9@" + A})
    assert res["status"] == "pinned"
    with pytest.raises(ValueError, match="pinned"):
        docker_updates._update_target("jellyfin/jellyfin@" + A)


def test_updating_a_pinned_app_pins_the_new_image(monkeypatch):
    from backend.services import compose_synthesizer

    monkeypatch.setattr(
        compose_synthesizer,
        "fetch_container_raw_inspect",
        lambda cid: {"Name": "/jf", "Config": {"Image": "jellyfin/jellyfin:latest@" + A, "Labels": FOLLOW}},
    )
    pulled, created = [], []
    monkeypatch.setattr(docker_updates, "pull_container_image", lambda img, timeout=0: pulled.append(img))
    monkeypatch.setattr(
        docker_updates, "recreate_container", lambda cid, image, **kw: created.append(image) or {"ok": True}
    )
    monkeypatch.setattr(
        docker_updates, "_docker_request", _fake_docker(B, ["other/repo@" + A, "jellyfin/jellyfin@" + B])
    )
    docker_updates.update_single_container("abc")
    assert pulled == ["jellyfin/jellyfin:latest"] and created == ["jellyfin/jellyfin:latest@" + B]


def test_updating_an_unpinned_app_keeps_its_tag(monkeypatch):
    from backend.services import compose_synthesizer

    monkeypatch.setattr(
        compose_synthesizer, "fetch_container_raw_inspect", lambda cid: {"Name": "/jf", "Config": {"Image": "nginx:1"}}
    )
    created = []
    monkeypatch.setattr(docker_updates, "pull_container_image", lambda img, timeout=0: None)
    monkeypatch.setattr(docker_updates, "recreate_container", lambda cid, image, **kw: created.append(image) or {})
    monkeypatch.setattr(docker_updates, "_docker_request", _fake_docker(B, ["library/nginx@" + B]))
    docker_updates.update_single_container("abc")
    assert created == ["nginx:1"]


def test_repin_keeps_the_tag_when_the_digest_is_unknown(monkeypatch):
    monkeypatch.setattr(docker_updates, "_docker_request", lambda m, p, **kw: (404, {}))
    assert docker_updates._repin("nginx:1") == "nginx:1"
    monkeypatch.setattr(docker_updates, "_docker_request", _fake_docker(B, ["library/nginx@" + B]))
    assert docker_updates._repin("nginx:1") == "nginx:1@" + B


def test_catalog_installs_carry_the_follow_tag_label(lock, monkeypatch, tmp_path):
    """The container create body of a pinned built-in app is labelled so updates follow its tag."""
    from backend.services import app_catalog

    with open(app_catalog.__file__, encoding="utf-8") as f:
        src = f.read()
    assert src.count('[FOLLOW_TAG_LABEL] = "1"') == 2  # main container and companions
