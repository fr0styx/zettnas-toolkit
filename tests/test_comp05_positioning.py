"""COMP-04, 05, 16, 10: the pages that lead with private search say only what the code does."""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import search_quality_page  # noqa: E402


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_search_quality_page_is_generated_from_the_baselines():
    assert _read("docs/SEARCH_QUALITY.md") == search_quality_page.render(), (
        "docs/SEARCH_QUALITY.md is out of date: python scripts/search_quality_page.py --update"
    )


def test_search_quality_page_shows_the_baseline_numbers():
    import json

    with open(os.path.join(ROOT, "tests", "rag_eval", "baseline.json"), encoding="utf-8") as fh:
        base = json.load(fh)
    page = _read("docs/SEARCH_QUALITY.md")
    o = base["overall"]
    assert f"| **All** | {o['queries']} | {o['recall@1']:.2f} | {o['recall@5']:.2f} |" in page


def test_rag_md_keeps_no_hand_copied_scores():
    rag = _read("docs/RAG.md")
    section = rag[rag.index("## Measured retrieval quality") : rag.index("## How answers are checked")]
    assert not re.search(r"\|\s*\*\*All\*\*\s*\|", section)
    assert "SEARCH_QUALITY.md" in section


def test_every_file_and_page_the_docs_name_exists():
    for page in ("docs/SAFE_AI.md", "docs/SEARCH_QUALITY.md", "README.md"):
        text = _read(page)
        base = os.path.dirname(os.path.join(ROOT, page))
        for target in re.findall(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)", text):
            if target.startswith("http"):
                continue
            assert os.path.exists(os.path.normpath(os.path.join(base, target))), (page, target)
        for test in re.findall(r"`(tests/[\w/]+\.py)`", text):
            assert os.path.exists(os.path.join(ROOT, test)), (page, test)


def test_safe_ai_claims_match_the_code():
    page = _read("docs/SAFE_AI.md")
    from backend.services import ai_actions

    assert "expires after 10\n  minutes" in page or "expires after 10 minutes" in page
    assert ai_actions.PROPOSAL_TTL_SECS == 10 * 60
    registry = _read("backend/services/chat_tool_registry.py")
    assert '"ai.tool." + ("confirmed" if confirmed else "call")' in registry
    assert "`ai.tool.call`, `ai.tool.confirmed`" in page
    options = re.findall(
        r'<option value="(\d+)"',
        _read("frontend/src/windows/management-window.html")
        .split('id="ai-conversation-retention-select"')[1]
        .split("</select>")[0],
    )
    assert options == ["0", "7", "30", "90", "365"]
    assert "7, 30, 90 or 365 days" in page


def test_readme_leads_with_private_search():
    readme = _read("README.md")
    first = readme[: readme.index("## What you get")]
    assert "privately" in first and "No\naccount, no subscription" in first.replace("No account", "No\naccount")
    assert "docs/SEARCH_QUALITY.md" in first and "docs/SAFE_AI.md" in first
    assert readme.split("## What you get")[1].lstrip().startswith("- **Ask Zetty**")


def test_the_wizard_welcome_leads_with_search_in_every_language():
    words = {"en": "No account", "de": "Kein Konto", "fr": "Sans compte", "es": "Sin cuenta", "zh": "无需账户"}
    for lang, phrase in words.items():
        text = _read(f"frontend/src/locales/{lang}.js")
        line = next(ln for ln in text.splitlines() if '"setup.welcome_desc"' in ln)
        assert "Zetty" in line and phrase in line, lang
    assert "Find any file by what is in it" in _read("frontend/index.html")
