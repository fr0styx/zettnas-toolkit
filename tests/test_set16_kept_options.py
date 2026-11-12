"""SET-16 stage 3: the owner's two Tailscale switches survive restarts; Disconnect wipes nothing."""

from backend.hardware.net import tailscale, tailscale_setup


def fake_settings(monkeypatch, start=None):
    store = dict(start or {})
    monkeypatch.setattr(tailscale, "settings", lambda: dict(store))
    monkeypatch.setattr(tailscale, "update_settings", lambda **f: store.update(f) or dict(store))
    return store


def test_the_switches_are_kept_when_they_apply(monkeypatch):
    store = fake_settings(monkeypatch)
    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", lambda cmd, timeout=8.0: (0, ""))
    tailscale.execute_tailscale_set_routes("192.168.1.0/24, 0.0.0.0/0", enabled=True)
    tailscale.execute_tailscale_set_exit_node(True)
    assert store == {"kept_routes": "192.168.1.0/24", "kept_exit_node": True}
    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", lambda cmd, timeout=8.0: (1, "denied"))
    tailscale.execute_tailscale_set_exit_node(False)
    assert store["kept_exit_node"] is True  # a change Tailscale refused is not kept


def test_reapply_sets_them_again(monkeypatch):
    fake_settings(monkeypatch, {"kept_routes": "192.168.1.0/24", "kept_exit_node": False})
    calls = []
    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", lambda cmd, timeout=8.0: (calls.append(cmd), (0, ""))[1])
    assert tailscale.reapply_kept() == ["--advertise-routes=192.168.1.0/24", "--advertise-exit-node=false"]
    assert calls == [["set", "--advertise-routes=192.168.1.0/24", "--advertise-exit-node=false"]]


def test_reapply_with_nothing_kept_runs_nothing(monkeypatch):
    fake_settings(monkeypatch)
    calls = []
    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", lambda cmd, timeout=8.0: (calls.append(cmd), (0, ""))[1])
    assert tailscale.reapply_kept() == [] and calls == []


def test_a_refused_reapply_says_nothing_was_set(monkeypatch):
    fake_settings(monkeypatch, {"kept_exit_node": True})
    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", lambda cmd, timeout=8.0: (1, "not running"))
    assert tailscale.reapply_kept() == []


def test_connecting_applies_them_after_the_reset(monkeypatch):
    applied = []
    monkeypatch.setattr(tailscale, "_get_tailscale_container_info", lambda: {"exists": False})
    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", lambda cmd, timeout=10.0: (0, ""))
    monkeypatch.setattr(tailscale, "reapply_kept", lambda: applied.append(1) or [])
    res = tailscale_setup.execute_tailscale_up(auth_key="tskey-test")
    assert res["status"] == "success" and applied == [1]


def test_disconnect_leaves_the_https_addresses(monkeypatch):
    from backend.services import remote_access

    ran = []
    monkeypatch.setattr(tailscale, "run_cli", lambda args, timeout=5.0: ran.append(args) or (0, ""))
    monkeypatch.setattr(tailscale_setup, "execute_tailscale_down", lambda: ran.append(["down"]) or {})
    monkeypatch.setattr(remote_access, "status", lambda: {"state": "Stopped"})
    assert remote_access.disconnect() == {"state": "Stopped"}
    assert ["serve", "reset"] not in ran and ["down"] in ran


def test_startup_does_not_poll_when_nothing_is_kept(monkeypatch):
    import backend.main as main

    fake_settings(monkeypatch)
    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    main._reapply_tailscale_options()
    assert slept == []


def test_startup_applies_them_once_tailscale_is_up(monkeypatch):
    import backend.main as main

    fake_settings(monkeypatch, {"kept_exit_node": True})
    monkeypatch.setattr("time.sleep", lambda s: None)
    up = iter([False, True])
    monkeypatch.setattr(tailscale, "installed", lambda: next(up))
    applied = []
    monkeypatch.setattr(tailscale, "reapply_kept", lambda: applied.append(1) or ["--advertise-exit-node=true"])
    main._reapply_tailscale_options()
    assert applied == [1]
