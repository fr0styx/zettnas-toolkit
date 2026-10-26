"""ARC-13: direct tests for the chat agent's NAS tools and tool-trace summaries."""

import json
import types

import pytest

from backend.services import chat_nas_tools as nt
from backend.services import chat_tool_registry as reg


@pytest.mark.parametrize(
    "trace, expected",
    [
        (
            {"tool": "get_system_telemetry", "cpu_load_pct": 5, "cpu_temp_c": 40, "ram_used_gb": 2, "ram_total_gb": 8},
            "CPU 5% (40°C), RAM 2/8 GB",
        ),
        (
            {"tool": "get_disks_and_standby_status", "running_disks_count": 2, "sleeping_disks_count": 3},
            "2 active, 3 sleeping in standby (0 wakeups)",
        ),
        (
            {"tool": "get_fan_and_thermal_status", "profile": "quiet", "temp_min_c": 35, "temp_max_c": 50},
            "Profile: quiet (35°C–50°C)",
        ),
        ({"tool": "set_fan_profile", "new_profile": "balanced"}, "Set profile to balanced"),
        ({"tool": "list_docker_containers", "running": 2, "total": 3}, "2/3 containers running"),
        ({"tool": "control_docker_container", "action": "restart", "container": "plex"}, "restart plex"),
        ({"tool": "trigger_ai_sync", "action": "pause"}, "Sync pause (Standby Safe)"),
        ({"tool": "browse_internet", "sources": [1, 2]}, "2 web source(s) verified"),
        ({"tool": "calculate", "expression": "2+2", "formatted": "4"}, "2+2 = 4"),
        ({"tool": "get_storage_status", "free_tib": 3.5}, "3.5 TiB free"),
        ({"tool": "get_network_status", "ip_address": "192.0.2.5"}, "IP: 192.0.2.5"),
        ({"tool": "get_weather", "location": "Oslo", "temperature_c": 4, "condition": "Rain"}, "Oslo: 4°C, Rain"),
        (
            {"tool": "get_weather", "is_ambiguous": True, "location": "Paris", "candidates": [1, 2]},
            "Ambiguous: Paris (2 countries available)",
        ),
        ({"tool": "something_else", "status": "done"}, "done"),
    ],
)
def test_every_tool_gets_a_one_line_summary(trace, expected):
    assert reg._format_tool_trace_summary(trace, trace["tool"]) == expected


def test_the_knowledge_search_summary_names_the_folder():
    out = reg._format_tool_trace_summary(
        {"tool": "search_nas_knowledge", "citations_count": 3, "photos_count": 1, "folder_path": "/Docs"},
        "search_nas_knowledge",
    )
    assert out.startswith("3 doc citations, 1 photos in /Docs (")


@pytest.mark.parametrize(
    "expr, formatted",
    [("what is 67+20", "87"), ("15% of 80", "12"), ("(2 + 3) * 4", "20"), ("2 ** 10", "1024"), ("-5 + 2", "-3")],
)
def test_the_calculator(expr, formatted):
    out = nt.tool_calculate(expr)
    assert out["status"] == "ok", out
    assert str(out["formatted"]) == formatted


@pytest.mark.parametrize("expr", ["", "1/0", "2 ** 100000", "__import__('os')", "open('x')", "a + 1", "'text' * 3"])
def test_the_calculator_refuses_what_it_cannot_do_safely(expr):
    assert nt.tool_calculate(expr)["status"] == "error"


def test_the_safe_evaluator_by_hand():
    import ast

    assert nt._eval_ast_math(ast.parse("abs(-3) + 1", mode="eval")) == 4.0
    for bad in ("x.y", "[1, 2]", "1 if 2 else 3"):
        with pytest.raises(ValueError):
            nt._eval_ast_math(ast.parse(bad, mode="eval"))


def test_fan_status_reads_the_saved_profile_and_pwm_channels(tmp_path, monkeypatch):
    from backend.state import Z_STATE

    fan_file = tmp_path / "fan_state.json"
    fan_file.write_text(json.dumps({"profile": "quiet", "temp_max": 55, "zero_rpm_enabled": True}))
    monkeypatch.setattr(nt, "FAN_STATE_FILE", str(fan_file))
    monkeypatch.setattr(Z_STATE, "fan_state_tracker", {"pwm1": {"current": 40}, "bad": 3})
    out = nt.tool_get_fan_and_thermal_status()
    assert out["profile"] == "quiet" and out["temp_max_c"] == 55 and out["zero_rpm_enabled"] is True
    assert out["pwm_channels"] == {"pwm1": 40} and out["cpu_fan_protected"] is True


def test_setting_the_fan_profile_needs_the_scope_and_a_known_profile(tmp_path, monkeypatch):
    fan_file = tmp_path / "fan_state.json"
    fan_file.write_text(json.dumps({"profile": "auto"}))
    monkeypatch.setattr(nt, "FAN_STATE_FILE", str(fan_file))
    assert nt.tool_set_fan_profile("quiet", principal=None)["status"] == "denied"
    admin = types.SimpleNamespace(scopes=["hardware:fans"])
    assert nt.tool_set_fan_profile("warp-speed", principal=admin)["status"] == "error"
    out = nt.tool_set_fan_profile("silent", zero_rpm_enabled=True, principal=admin)
    assert out["status"] == "ok" and out["new_profile"] == "quiet" and out["previous_profile"] == "auto"
    assert out["zero_rpm_enabled"] is True


def test_listing_containers_outside_test_mode(monkeypatch):
    from backend.hardware import docker_stats

    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setenv("ZETTNAS_TEST_MODE", "0")
    monkeypatch.setattr(
        docker_stats,
        "read_docker_containers",
        lambda force=False: [
            {"name": "plex", "image": "plex:1", "state": "running", "status": "Up 3 days", "created": 100},
            {"name": "old", "image": "x:1", "state": "exited", "status": "Exited (0)", "created": 50},
        ],
    )
    out = nt.tool_list_docker_containers()
    assert out["status"] == "ok"
    assert out["total"] == 2 and out["running"] == 1
    assert {c["name"] for c in out["containers"]} == {"plex", "old"}
