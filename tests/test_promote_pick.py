"""The promotion workflow picks the newest beta that has soaked (OPS-2)."""

import datetime as dt
import json
import os
import shutil
import stat
import subprocess

import pytest
import yaml

WF = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "promote.yml")
pytestmark = pytest.mark.skipif(not shutil.which("jq"), reason="needs jq (present on CI runners)")


def _iso(days_ago):
    return (dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pick(tmp_path, releases, want="", skip="false", hold="", event="", today=""):
    with open(WF, encoding="utf-8") as f:
        steps = yaml.safe_load(f)["jobs"]["promote"]["steps"]
    script = next(s for s in steps if s.get("id") == "pick")["run"].replace("${{ github.repository }}", "o/r")
    tmp_path.mkdir(exist_ok=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    (tmp_path / "rel.json").write_text(json.dumps(releases))
    gh.write_text(f"#!/bin/sh\ncat {tmp_path / 'rel.json'}\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    out, summ = tmp_path / "out", tmp_path / "summ"
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(out),
        "GITHUB_STEP_SUMMARY": str(summ),
        "WANT": want,
        "SKIP": skip,
        "HOLD": hold,
        "SOAK_DAYS": "3",
        "EVENT": event,
        "TRAIN_TODAY": today,
    }
    p = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line), p.stdout


def _rel(tag, days, pre=True, rid=1):
    return {
        "tag_name": tag,
        "prerelease": pre,
        "draft": False,
        "created_at": _iso(days),
        "published_at": _iso(days),
        "id": rid,
        "name": f"{tag} (beta)",
    }


def test_a_newer_beta_in_its_soak_does_not_block_an_older_ready_one(tmp_path):
    out, _ = _pick(tmp_path, [_rel("v1.9.6", 1), _rel("v1.9.5", 9), _rel("v1.9.3", 30, pre=False)])
    assert out["go"] == "true" and out["tag"] == "v1.9.5"


def test_held_betas_are_skipped(tmp_path):
    out, _ = _pick(tmp_path, [_rel("v1.9.5", 9), _rel("v1.9.4", 12), _rel("v1.9.3", 30, pre=False)], hold="v1.9.5")
    assert out["tag"] == "v1.9.4"


def test_warns_when_stable_is_stale(tmp_path):
    out, stdout = _pick(tmp_path, [_rel("v1.9.6", 2), _rel("v1.9.3", 50, pre=False)])
    assert out["go"] == "false" and "Stable is stale" in stdout
    out, stdout = _pick(tmp_path / "b", [_rel("v1.9.6", 2), _rel("v1.9.3", 10, pre=False)])
    assert "Stable is stale" not in stdout  # a missed weekly train is normal


def test_manual_security_promotion_skips_the_soak(tmp_path):
    out, _ = _pick(tmp_path, [_rel("v1.9.4", 0), _rel("v1.9.3", 30, pre=False)], want="v1.9.4", skip="true")
    assert out["go"] == "true" and out["tag"] == "v1.9.4"


# --- the weekly train (COMP-10) ---

READY = [_rel("v1.9.5", 9), _rel("v1.9.3", 40, pre=False)]


@pytest.mark.parametrize("today", ["2026-11-03", "2026-11-10", "2026-11-24"])  # Tuesdays
def test_the_schedule_promotes_every_tuesday(tmp_path, today):
    out, _ = _pick(tmp_path, READY, event="schedule", today=today)
    assert out["go"] == "true" and out["tag"] == "v1.9.5"


def test_three_days_on_beta_is_enough(tmp_path):
    out, _ = _pick(tmp_path, [_rel("v1.9.6", 3), _rel("v1.9.3", 40, pre=False)], event="schedule", today="2026-11-10")
    assert out["go"] == "true" and out["tag"] == "v1.9.6"
    out, _ = _pick(
        tmp_path / "b", [_rel("v1.9.6", 2), _rel("v1.9.3", 40, pre=False)], event="schedule", today="2026-11-10"
    )
    assert out["go"] == "false"


@pytest.mark.parametrize("today", ["2026-11-04", "2026-11-09", "2026-12-07"])
def test_the_schedule_waits_for_the_train_on_other_days(tmp_path, today):
    out, stdout = _pick(tmp_path, READY, event="schedule", today=today)
    assert out["go"] == "false" and "next stable train" in stdout


def test_the_next_train_is_named(tmp_path):
    _, stdout = _pick(tmp_path, READY, event="schedule", today="2026-11-04")
    assert "2026-11-10" in stdout


def test_a_run_by_hand_is_not_held_for_the_train(tmp_path):
    out, _ = _pick(tmp_path, READY, event="workflow_dispatch", today="2026-11-11")
    assert out["go"] == "true" and out["tag"] == "v1.9.5"
