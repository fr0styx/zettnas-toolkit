#!/usr/bin/env python3
"""Reports CI update notices: newer versions and deprecations that CI runs mention.

Run by .github/workflows/ci-notices.yml after each CI run on main and weekly. It:
  * scans a CI run's logs and annotations for "newer version available", deprecation and
    similar notices (lint warnings and known noise are skipped);
  * compares each action in .github/workflows to its latest release;
  * compares versions Dependabot does not update (Trivy's `version:` input, .nvmrc) to the
    latest releases.

The findings go to the job summary and to one issue titled "CI update notices", which is
updated when they change and closed when there are none. Accepted notices can be silenced
with regular expressions in .github/ci-notices-ignore (one per line, # for comments).

Uses only the standard library. Needs GITHUB_TOKEN and GITHUB_REPOSITORY.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

API = "https://api.github.com"
ISSUE_TITLE = "CI update notices"
CI_WORKFLOW = "ci.yml"
ROOT = Path(__file__).resolve().parent.parent

NOTICE_RE = re.compile(
    r"newer version|new version|is now available|update available|upgrade to|outdated"
    r"|deprecat|end[- ]of[- ]life|no longer supported|will be removed|will migrate|please update",
    re.IGNORECASE,
)
# Lines that match NOTICE_RE but are not notices
NOISE_RE = re.compile(
    r"no-unused-vars"  # ESLint warnings: tracked by the lint budget
    r"|\x1b\[36;1m|\[36;1m"  # a step's script echoed before it runs
    r"|NODE_OPTIONS: --no-deprecation"
    r"|running outdated (binaries|hypervisor)"  # needrestart's all-clear
    r"|To suppress version checks",
    re.IGNORECASE,
)
TIMESTAMP_RE = re.compile(r"^﻿?\d{4}-\d\d-\d\dT[\d:.]+Z\s?")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
USES_RE = re.compile(r"uses:\s*([\w.-]+/[\w.-]+)(?:/[\w./-]+)?@([\w.-]+)(?:\s*#\s*(v?[\d.]+))?")
VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)")


# ---------- pure helpers (unit-tested) ----------


def clean_line(line: str) -> str:
    line = ANSI_RE.sub("", TIMESTAMP_RE.sub("", line)).strip()
    if len(line) > 1 and line[0] == line[-1] == '"':  # annotations can arrive quoted
        line = line[1:-1].strip()
    return line


def find_notices(lines: list[str], ignore: list[re.Pattern[str]] | None = None) -> list[str]:
    """The notice lines in a log, cleaned and without duplicates, in order."""
    seen: dict[str, None] = {}
    for raw in lines:
        if NOISE_RE.search(raw):
            continue
        line = clean_line(raw)
        line = re.sub(r"^(##\[(warning|notice)\]|::(warning|notice)[^:]*::)", "", line).strip()
        if not line or not NOTICE_RE.search(line):
            continue
        if ignore and any(p.search(line) for p in ignore):
            continue
        seen.setdefault(line[:300], None)
    return list(seen)


def version_tuple(text: str) -> tuple[int, ...] | None:
    m = VERSION_RE.fullmatch(text.strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def is_behind(current: str, latest: str) -> bool:
    """True when `latest` is newer. A bare major tag (v7) only lags behind a newer major."""
    cur, new = version_tuple(current), version_tuple(latest)
    if cur is None or new is None:
        return False
    if len(cur) == 1:
        return new[0] > cur[0]
    width = max(len(cur), len(new))
    return new + (0,) * (width - len(new)) > cur + (0,) * (width - len(cur))


def action_refs(workflow_text: str) -> list[tuple[str, str]]:
    """(owner/repo, version in use) for each action; a commit pin uses its # vX.Y.Z comment."""
    out: list[tuple[str, str]] = []
    for m in USES_RE.finditer(workflow_text):
        repo, ref, comment = m.group(1), m.group(2), m.group(3)
        version = comment if re.fullmatch(r"[0-9a-f]{40}", ref) else ref
        if version and version_tuple(version) is not None:
            out.append((repo, version))
    return out


def trivy_version(workflow_text: str) -> str | None:
    """The Trivy version given to trivy-action, or the action's default if none is set."""
    lines = workflow_text.splitlines()
    for i, line in enumerate(lines):
        if not re.search(r"uses:\s*aquasecurity/trivy-action@", line):
            continue
        for nxt in lines[i + 1 :]:
            if re.match(r"\s*-\s", nxt):  # the next step
                break
            m = re.match(r"\s*version:\s*['\"]?(v?[\d.]+)", nxt)
            if m:
                return m.group(1)
        return "v0.70.0 (action default)"
    return None


def load_ignore(path: Path) -> list[re.Pattern[str]]:
    if not path.exists():
        return []
    pats = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            pats.append(re.compile(line, re.IGNORECASE))
    return pats


def render(run: dict[str, Any] | None, behind: list[str], notices: dict[str, list[str]], job_count: int = 0) -> str:
    """Markdown for the issue and job summary; empty when there is nothing to report.

    `notices` maps each notice to the jobs that printed it.
    """
    parts = []
    if behind:
        parts.append("### Newer versions\n\n" + "\n".join(f"- {b}" for b in behind))
    if notices:
        src = f"[CI run {run['run_number']}]({run['html_url']})" if run else "the latest CI run"
        items = []
        for text, jobs in notices.items():
            where = "all jobs" if job_count and len(jobs) >= job_count else ", ".join(jobs)
            safe = text.replace("`", "'")
            items.append(f"- `{safe}` ({where})")
        parts.append(f"### Notices in {src}\n\n" + "\n".join(items))
    if not parts:
        return ""
    footer = (
        "\n\n---\nUpdated by the CI notices workflow (`scripts/ci_notices.py`). "
        "Accepted notices can be silenced in `.github/ci-notices-ignore`."
    )
    return "\n\n".join(parts) + footer


# ---------- GitHub access ----------


class GitHub:
    def __init__(self, token: str, repo: str) -> None:
        self.repo = repo
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "zettnas-ci-notices",
        }

    def call(self, method: str, path: str, data: dict[str, Any] | None = None, raw: bool = False) -> Any:
        url = path if path.startswith("http") else API + path
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method=method, headers=self.headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            content = resp.read()
        return content if raw else (json.loads(content) if content else None)

    def latest_release(self, repo: str) -> str | None:
        try:
            return self.call("GET", f"/repos/{repo}/releases/latest")["tag_name"]
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
        tags = self.call("GET", f"/repos/{repo}/tags?per_page=30") or []
        versions = [t["name"] for t in tags if version_tuple(t["name"])]
        return max(versions, key=lambda v: version_tuple(v) or (0,)) if versions else None


def latest_node(major: int) -> str | None:
    req = urllib.request.Request("https://nodejs.org/dist/index.json", headers={"User-Agent": "zettnas-ci-notices"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        releases = json.load(resp)
    same = [r["version"] for r in releases if (version_tuple(r["version"]) or (0,))[0] == major]
    return max(same, key=lambda v: version_tuple(v) or (0,)) if same else None


def check_versions(gh: GitHub) -> list[str]:
    behind: list[str] = []
    seen: set[tuple[str, str]] = set()
    trivy = None
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = wf.read_text()
        trivy = trivy or trivy_version(text)
        for repo, current in action_refs(text):
            if (repo, current) in seen:
                continue
            seen.add((repo, current))
            latest = gh.latest_release(repo)
            if latest and is_behind(current, latest):
                behind.append(f"`{repo}` {current} → {latest} ({wf.name})")
    if trivy:
        latest = gh.latest_release("aquasecurity/trivy")
        if latest and is_behind(trivy.split()[0], latest):
            behind.append(f"Trivy {trivy} → {latest} (set `version:` on trivy-action in ci.yml)")
    nvmrc = ROOT / ".nvmrc"
    if nvmrc.exists():
        current = nvmrc.read_text().strip()
        cur = version_tuple(current)
        latest = latest_node(cur[0]) if cur else None
        if latest and is_behind(current, latest):
            behind.append(f"Node.js {current} → {latest} (.nvmrc, the Dockerfile and package.json engines)")
    return behind


def scan_run(gh: GitHub, run: dict[str, Any], ignore: list[re.Pattern[str]]) -> tuple[dict[str, list[str]], int]:
    """Notices in a run's annotations and logs, each with the jobs that printed it."""
    notices: dict[str, list[str]] = {}

    def add(job: str, found: list[str]) -> None:
        for text in found:
            jobs = notices.setdefault(text, [])
            if job not in jobs:
                jobs.append(job)

    jobs = gh.call("GET", f"/repos/{gh.repo}/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]
    for job in jobs:
        anns = gh.call("GET", f"/repos/{gh.repo}/check-runs/{job['id']}/annotations?per_page=100") or []
        add(
            job["name"],
            find_notices([a["message"] for a in anns if a.get("annotation_level") in ("notice", "warning")], ignore),
        )
    archive = zipfile.ZipFile(io.BytesIO(gh.call("GET", f"/repos/{gh.repo}/actions/runs/{run['id']}/logs", raw=True)))
    for name in sorted(archive.namelist()):
        if name.count("/") != 1:  # per-step files only; the top-level ones repeat them
            continue
        add(name.split("/")[0], find_notices(archive.read(name).decode("utf-8", "replace").splitlines(), ignore))
    ran = [j for j in jobs if j.get("conclusion") != "skipped"]
    return notices, len(ran)


def update_issue(gh: GitHub, body: str) -> str:
    issues = gh.call("GET", f"/repos/{gh.repo}/issues?state=open&per_page=100") or []
    issue = next((i for i in issues if i["title"] == ISSUE_TITLE and "pull_request" not in i), None)
    if not body:
        if issue:
            gh.call(
                "POST", f"/repos/{gh.repo}/issues/{issue['number']}/comments", {"body": "No notices left; closing."}
            )
            gh.call("PATCH", f"/repos/{gh.repo}/issues/{issue['number']}", {"state": "closed"})
            return f"closed issue #{issue['number']}"
        return "nothing to report"
    if issue:
        if (issue.get("body") or "").strip() == body.strip():
            return f"issue #{issue['number']} unchanged"
        gh.call("PATCH", f"/repos/{gh.repo}/issues/{issue['number']}", {"body": body})
        return f"updated issue #{issue['number']}"
    made = gh.call("POST", f"/repos/{gh.repo}/issues", {"title": ISSUE_TITLE, "body": body})
    return f"opened issue #{made['number']}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", default="", help="CI run to scan (default: the latest completed run on main)")
    ap.add_argument("--no-issue", action="store_true", help="only print and write the job summary")
    args = ap.parse_args(argv)

    token, repo = os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("GITHUB_TOKEN and GITHUB_REPOSITORY are required", file=sys.stderr)
        return 2
    gh = GitHub(token, repo)
    ignore = load_ignore(ROOT / ".github" / "ci-notices-ignore")

    if args.run_id:
        run = gh.call("GET", f"/repos/{repo}/actions/runs/{args.run_id}")
    else:
        runs = gh.call(
            "GET", f"/repos/{repo}/actions/workflows/{CI_WORKFLOW}/runs?branch=main&status=completed&per_page=1"
        )
        run = (runs.get("workflow_runs") or [None])[0]

    behind = check_versions(gh)
    notices, job_count = scan_run(gh, run, ignore) if run else ({}, 0)
    body = render(run, behind, notices, job_count)

    print(body or "No update notices.")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"## {ISSUE_TITLE}\n\n{body or 'No update notices.'}\n")
    for line in behind:
        print(f"::warning title=Newer version::{line}")
    if not args.no_issue:
        print(update_issue(gh, body))
    return 0


if __name__ == "__main__":
    sys.exit(main())
