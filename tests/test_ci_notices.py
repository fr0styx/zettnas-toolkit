"""scripts/ci_notices.py: finds update notices in CI logs and newer versions of pinned tools."""

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("ci_notices", ROOT / "scripts" / "ci_notices.py")
assert _spec and _spec.loader
cn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cn)


def test_finds_version_and_deprecation_notices_and_skips_noise():
    log = [
        "2026-10-22T18:35:01.1Z   - Version 0.76.1 of Trivy is now available, current version is 0.70.0",
        "2026-10-22T18:35:01.2Z To suppress version checks, run Trivy scans with the --skip-version-check flag",
        "2026-10-22T18:30:00.0Z ##[warning]  13:7  warning  'x' is assigned a value but never used  no-unused-vars",
        '2026-10-22T18:30:00.0Z \x1b[36;1m    log_error "cosign versions below v2.0.0 are no longer supported."\x1b[0m',
        "2026-10-22T18:30:00.0Z No user sessions are running outdated binaries.",
        "2026-10-22T18:30:00.0Z   NODE_OPTIONS: --no-deprecation",
        "2026-10-22T18:31:00.0Z app.py:152: FastAPIDeprecationWarning: ORJSONResponse is deprecated",
        "2026-10-22T18:31:00.5Z app.py:152: FastAPIDeprecationWarning: ORJSONResponse is deprecated",
        "2026-10-22T18:32:00.0Z ##[notice]The ubuntu-latest label will migrate to Ubuntu 26 beginning October 19, 2026.",
        "2026-10-22T18:33:00.0Z all tests passed",
        "2026-10-22T18:33:00.1Z tests/test_x.py::test_skips_deprecation_noise PASSED [ 26%]",
        '"Node.js 20 is deprecated"',
    ]
    assert cn.find_notices(log) == [
        "- Version 0.76.1 of Trivy is now available, current version is 0.70.0",
        "app.py:152: FastAPIDeprecationWarning: ORJSONResponse is deprecated",
        "The ubuntu-latest label will migrate to Ubuntu 26 beginning October 19, 2026.",
        "Node.js 20 is deprecated",
    ]


def test_ignore_patterns_silence_accepted_notices(tmp_path):
    f = tmp_path / "ignore"
    f.write_text("# comment\n\nubuntu-latest label will migrate\n")
    lines = ["The ubuntu-latest label will migrate to Ubuntu 26", "Foo is deprecated"]
    assert cn.find_notices(lines, cn.load_ignore(f)) == ["Foo is deprecated"]


def test_version_comparison():
    assert cn.is_behind("v0.70.0", "v0.76.1")
    assert not cn.is_behind("v0.76.1", "v0.76.1")
    assert cn.is_behind("26.12.1", "v26.12.2")
    assert not cn.is_behind("v7", "v7.3.0")  # a major tag already follows its minors
    assert cn.is_behind("v7", "v8.0.0")
    assert cn.is_behind("v4.1", "v4.1.2")
    assert not cn.is_behind("main", "v2")


def test_reads_action_versions_and_the_trivy_input():
    wf = """
    steps:
      - uses: actions/checkout@v7
      - uses: docker/build-push-action@v7
      - uses: github/codeql-action/init@v4
      - uses: aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25 # v0.36.0
        with:
          version: v0.76.1
          image-ref: x
      - uses: some/action@main
    """
    assert cn.action_refs(wf) == [
        ("actions/checkout", "v7"),
        ("docker/build-push-action", "v7"),
        ("github/codeql-action", "v4"),
        ("aquasecurity/trivy-action", "v0.36.0"),
    ]
    assert cn.trivy_version(wf) == "v0.76.1"
    assert cn.trivy_version(wf.replace("          version: v0.76.1\n", "")) == "v0.70.0 (action default)"


def test_render_groups_jobs_and_is_empty_when_clean():
    run = {"run_number": 7, "html_url": "https://example/run/7"}
    body = cn.render(
        run, ["Trivy v0.70.0 → v0.76.1"], {"Ubuntu 26 `soon`": ["A", "B"], "X deprecated": ["A"]}, job_count=2
    )
    assert "### Newer versions" in body and "Trivy v0.70.0 → v0.76.1" in body
    assert "[CI run 7](https://example/run/7)" in body
    assert "- `Ubuntu 26 'soon'` (all jobs)" in body
    assert "- `X deprecated` (A)" in body
    assert cn.render(run, [], {}) == ""


def test_ci_pins_a_current_trivy():
    wf = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    v = cn.trivy_version(wf)
    assert v and not v.endswith("(action default)"), "set version: on trivy-action"
    assert cn.version_tuple(v) >= (0, 76, 1)


def test_notices_workflow_is_scoped():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci-notices.yml").read_text())
    on = wf.get("on") or wf.get(True)
    assert on["workflow_run"]["workflows"] == ["CI & Release"]
    assert on["workflow_run"]["branches"] == ["main"]
    assert "schedule" in on and "workflow_dispatch" in on
    assert wf["permissions"] == {"actions": "read", "checks": "read", "contents": "read", "issues": "write"}
    job = wf["jobs"]["notices"]
    assert "head_repository.full_name == github.repository" in job["if"]
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    assert ci["name"] == "CI & Release"


def test_server_errors_are_retried_and_client_errors_are_not(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    calls = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def flaky(req, timeout=60):
        calls.append(req.full_url)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, None)
        return Resp(b'{"ok": true}')

    monkeypatch.setattr(cn.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(cn.time, "sleep", lambda s: None)
    req = urllib.request.Request("https://api.github.com/x")
    assert cn.open_url(req) == b'{"ok": true}' and len(calls) == 3

    def missing(req, timeout=60):
        calls.append("404")
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    calls.clear()
    monkeypatch.setattr(cn.urllib.request, "urlopen", missing)
    try:
        cn.open_url(req)
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
    assert calls == ["404"]

    def down(req, timeout=60):
        calls.append("down")
        raise urllib.error.HTTPError(req.full_url, 503, "Unavailable", {}, None)

    calls.clear()
    monkeypatch.setattr(cn.urllib.request, "urlopen", down)
    try:
        cn.open_url(req, retries=2)
    except urllib.error.HTTPError as exc:
        assert exc.code == 503
    assert len(calls) == 3
