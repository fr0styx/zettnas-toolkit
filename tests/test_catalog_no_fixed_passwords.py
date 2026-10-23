"""Catalog apps never start with a fixed, published password."""

from unittest.mock import patch

from backend.services import app_catalog

SECRET_WORDS = ("PASS", "SECRET", "TOKEN", "KEY")


def test_no_template_sets_a_fixed_password():
    for app in app_catalog.CURATED_APP_CATALOG:
        for key, value in (app.get("env") or {}).items():
            if any(w in key.upper() for w in SECRET_WORDS):
                raise AssertionError(f"{app['id']} sets {key} to a fixed value")


def test_pihole_install_says_where_its_password_is(tmp_path):
    app = next(a for a in app_catalog.CURATED_APP_CATALOG if a["id"] == "pihole")

    def fake_docker(method, path, *args, **kwargs):
        if "/containers/create" in path:
            env = kwargs["body"]["Env"]
            assert not any(e.split("=", 1)[0].upper() in ("WEBPASSWORD", "FTLCONF_WEBSERVER_API_PASSWORD") for e in env)
            return 201, {"Id": "cid"}
        if path.startswith("/images/"):
            return 200, {}
        if path.endswith("/json"):
            return (200, {"State": {"Running": True}}) if "cid" in path else (404, {})
        return 204, {}

    with (
        patch.object(app_catalog, "get_catalog_app", return_value=app),
        patch.object(app_catalog, "_docker_request", side_effect=fake_docker),
        patch.object(app_catalog, "check_port_available_detailed", return_value=(True, None)),
    ):
        events = list(app_catalog.stream_deploy_catalog_app("pihole", host_port=18081, storage_root=str(tmp_path)))
    assert events[-1]["step"] == "success", events[-1]
    assert "container's log" in events[-1]["message"]
