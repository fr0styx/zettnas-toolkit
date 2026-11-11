"""SET-02: "Turn on HTTPS" pressed on the HTTPS address itself does not save 443 as Kiboto's port."""

from backend.hardware.net import tailscale
from backend.services import remote_access


def _publish(monkeypatch, tmp_path, port):
    monkeypatch.setattr(tailscale, "SETTINGS_FILE", str(tmp_path / "remote_access.json"))
    monkeypatch.setattr(remote_access, "status", lambda: {"state": "Running", "https": False})
    remote_access.publish(app_port=port)
    return tailscale.settings().get("app_port")


def test_the_port_of_the_https_address_is_not_kibotos(monkeypatch, tmp_path):
    assert _publish(monkeypatch, tmp_path, 8082) == 8082
    assert _publish(monkeypatch, tmp_path, 443) == 8082  # kept
    assert remote_access._app_port() == 8082


def test_a_kiboto_that_listens_on_443_keeps_it(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.settings.current", lambda key: 443 if key == "port" else None)
    assert _publish(monkeypatch, tmp_path, 443) == 443
