"""A Funnel command that waits for the tailnet owner's approval returns its output (the link) in
time: it is cut off below the Docker exec connection's 10 s, whatever the caller asked for."""

from backend.hardware.net import tailscale


def test_a_waiting_funnel_command_is_cut_off_inside_the_exec_time(monkeypatch):
    seen = []

    def fake_exec(name, cmd):
        seen.append(cmd)
        return {
            "success": True,
            "exit_code": 124,
            "output": "Funnel is not enabled on your tailnet.\nTo enable, visit:\n https://login.tailscale.com/f/funnel?node=abc",
        }

    import backend.services.compose_synthesizer as cs

    monkeypatch.setattr(tailscale, "_get_tailscale_container_info", lambda: {"exists": True, "running": True})
    monkeypatch.setattr(cs, "execute_in_container", fake_exec)
    code, out = tailscale._run_tailscale_cmd(
        ["funnel", "--bg", "--yes", "--https=10000", "http://127.0.0.1:1"], timeout=15.0
    )
    assert seen[0][:2] == ["timeout", str(tailscale.EXEC_WAIT_CAP)] and tailscale.EXEC_WAIT_CAP < 10
    assert "login.tailscale.com/f/funnel" in out and code == 124
    tailscale._run_tailscale_cmd(["funnel", "status", "--json"], timeout=15.0)
    assert seen[1][0] == "tailscale"  # a status read is never wrapped
    tailscale._run_tailscale_cmd(["serve", "--bg", "--https=443", "http://127.0.0.1:2"], timeout=3.0)
    assert seen[2][:2] == ["timeout", "3"]
