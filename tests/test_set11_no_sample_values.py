"""SET-11: the markup carries no sample values.

The pages shipped with believable readings written into their markup: "Score: 100/100",
"v1.9.1 • Stable", "Online", a board name, a processor, a UPS. A script was meant to write the
real value over each. When its load failed, or before it ran, the sample stood there as if it were
measured. Every element a script writes now starts as a dash, or as a prompt that claims nothing."""

import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ("frontend/src/windows/management-window.html", "frontend/index.html")

# prompts and "still looking" words that are true before anything is known; adding to this list
# is a claim that the text is no reading
PROMPTS = {
    "mgmt-sidebar-storage-badge": "Drives",
    "mgmt-sidebar-ups-badge": "Power",
    "tailscale-status-badge": "Checking...",
    "btn-jump-to-2fa": "Configure 2FA →",
    "about-chassis-model": "Detecting...",
    "about-host-platform": "Detecting...",
    "update-status-title": "Update check pending",
    "update-release-title": "New Release Available",
    "btn-revert-update-text": "Revert to previous version",
    "update-progress-desc": "Downloading the new version and restarting Kiboto.",
    "ai-chat-active-title": "New Conversation",
    "ai-llm-advisor-headline": "NPU + GPU Advisor",
    "ai-hw-tier1-status": "Probing NPU...",
    "ai-hw-tier2-status": "Probing GPU...",
    "ai-watched-dropdown-summary": "Select Watched Folders for RAG...",
    "notif-modal-title": "Configure Alert Channel",
    "sftp-status-text": "Status: Checking...",
    "btn-sftp-toggle-service": "Start SFTP",
    "w-weather-desc": "Loading…",
    "setup-hw-chassis": "Detecting...",
    "copy-toast-file": "Preparing files...",
    "copy-toast-time": "Estimating time...",
}
LONG_PROMPTS = {"ts-form-intro", "update-status-desc", "ai-llm-advisor-summary", "net-bond-mode-desc"}  # sentences


def _scripts() -> str:
    out = []
    for path in glob.glob(os.path.join(ROOT, "frontend", "src", "**", "*.js"), recursive=True):
        if "__tests__" not in path:
            with open(path, encoding="utf-8") as fh:
                out.append(fh.read())
    return "\n".join(out)


def _written_samples():
    js = _scripts()
    for page in PAGES:
        with open(os.path.join(ROOT, page), encoding="utf-8") as fh:
            html = fh.read()
        for m in re.finditer(r"<(\w+)([^>]*\sdata-sample\b[^>]*)>([^<]*)", html):
            tag, attrs, text = m.group(1), m.group(2), m.group(3).strip()
            ident = (re.search(r'\sid="([^"]+)"', attrs) or [None, ""])[1]
            if tag in ("input", "textarea", "option", "select") or not ident:
                continue
            if f"'{ident}'" in js or f'"{ident}"' in js or f"#{ident}" in js:
                yield page, ident, text


def test_what_a_script_writes_starts_as_a_dash_or_a_prompt():
    wrong = []
    for page, ident, text in _written_samples():
        if ident.startswith("lcd-"):  # the front screen's own page is left as it is
            continue
        if text in ("", "—") or ident in LONG_PROMPTS or PROMPTS.get(ident) == text:
            continue
        wrong.append(f"{page}: #{ident} starts as {text!r}")
    assert not wrong, "sample values in the markup (use a dash):\n" + "\n".join(wrong)


def test_the_samples_the_reviews_named_are_gone():
    pages = ""
    for page in PAGES:
        with open(os.path.join(ROOT, page), encoding="utf-8") as fh:
            pages += fh.read()
    for sample in (
        "Score: 100/100",
        "v1.9.1",
        "Zettlab WY120",
        "18 Threads",
        "Generic UPS",
        "Intel Arc Graphics",
        "CYBER TEAL",
    ):
        assert sample not in pages, sample
