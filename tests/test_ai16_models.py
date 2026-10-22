"""AI-03 / AI-16: installing a model really downloads it, and copies are reported, not deleted."""

import io
import json
import time

from backend.services import model_installer as mi


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_runtime(monkeypatch, pulled_ok=True, listed_after=True):
    state = {"installed": [{"name": "qwen2.5:3b", "digest": "d1"}, {"name": "Underdog-27B:latest", "digest": "d1"}]}

    def urlopen(req, timeout=None):
        url = req.full_url
        if url.endswith("/api/tags"):
            return _Resp(json.dumps({"models": state["installed"]}).encode())
        if url.endswith("/api/pull"):
            body = json.loads(req.data)
            lines = [
                {"status": "pulling manifest"},
                {"status": "downloading", "digest": "a", "total": 100, "completed": 50},
                {"status": "downloading", "digest": "a", "total": 100, "completed": 100},
            ]
            if pulled_ok:
                lines.append({"status": "success"})
                if listed_after:
                    state["installed"].append({"name": body["model"], "digest": "d2"})
            else:
                lines.append({"error": "pull model manifest: file does not exist"})
            return _Resp(("\n".join(json.dumps(x) for x in lines) + "\n").encode())
        raise OSError("unexpected " + url)

    monkeypatch.setattr(mi, "_host", lambda: "http://ollama:11434")
    monkeypatch.setattr(mi.urllib.request, "urlopen", urlopen)
    return state


def _wait(job_id):
    for _ in range(100):
        job = mi.get_job(job_id)
        if job["state"] not in ("starting", "downloading", "verifying"):
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_install_downloads_and_verifies(monkeypatch):
    _fake_runtime(monkeypatch)
    job = _wait(mi.start_install("llama3.2:3b")["id"])
    assert job["state"] == "done" and job["percent"] == 100.0 and job["total_bytes"] == 100


def test_install_reports_runtime_errors(monkeypatch):
    _fake_runtime(monkeypatch, pulled_ok=False)
    job = _wait(mi.start_install("nope:1b")["id"])
    assert job["state"] == "failed" and "does not exist" in job["error"]


def test_install_fails_if_model_not_listed_afterwards(monkeypatch):
    _fake_runtime(monkeypatch, listed_after=False)
    job = _wait(mi.start_install("ghost:1b")["id"])
    assert job["state"] == "failed" and "doesn't list" in job["error"]


def test_bad_names_are_refused():
    import pytest

    for bad in ("", "../etc", "a b", "-x", "x" * 300):
        with pytest.raises(ValueError):
            mi.start_install(bad)


def test_aliases_are_reported_not_deleted(monkeypatch):
    _fake_runtime(monkeypatch)
    inst = mi.installed_models()
    assert inst["reachable"] is True
    assert inst["aliases"] == [{"name": "Underdog-27B:latest", "same_as": "qwen2.5:3b"}]
    assert mi.is_installed("qwen2.5:3b", inst["models"]) and not mi.is_installed("llama3.2:3b", inst["models"])
