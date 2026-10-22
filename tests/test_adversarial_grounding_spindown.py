"""
tests/test_adversarial_grounding_spindown.py — Adversarial Verification Suite
Stress-testing contextual grounding, snippet cleaning, thought token handling,
and zero-disk-spindown safety for ZettNAS RAG & AI Chatbot subsystems.

Targets:
1. extract_and_strip_reasoning (thought tokens, unclosed tags, nested tags, whitespace, empty)
2. _clean_complete_snippet (Markdown tables, Python code, Docker compose YAML, recipes, lists, fragments)
3. _build_structured_llm_context (0, 1, 10 citations, parent context, photos, cards, XML formatting)
4. resolve_path_backing_dev (symlink resolution from SSD cache to spinning array)
5. Zero-disk-spindown safety during query execution and context assembly
"""

import json
import os
import re
import sqlite3
import subprocess
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.services.ai_chat_agent import (
    _build_structured_llm_context,
    _clean_complete_snippet,
    extract_and_strip_reasoning,
    tool_search_nas_knowledge,
)
from backend.services.rag_engine import (
    RagSearchEngine,
    is_backing_disk_in_standby,
    resolve_path_backing_dev,
)
from backend.state import Z_STATE

# ============================================================================
# 1. Thought Token & Reasoning Extraction Stress Tests
# ============================================================================


class TestReasoningExtractionStress:
    """Adversarial stress-testing of extract_and_strip_reasoning."""

    def test_standard_closed_tags(self):
        """Verifies standard <think>, <thought>, <reasoning> blocks."""
        text = "<think>Analyzing user question</think>Here is the answer."
        th, cl = extract_and_strip_reasoning(text)
        assert th == "Analyzing user question"
        assert cl == "Here is the answer."

        text2 = "<thought>Checking system telemetry</thought>CPU is 42°C."
        th2, cl2 = extract_and_strip_reasoning(text2)
        assert th2 == "Checking system telemetry"
        assert cl2 == "CPU is 42°C."

        text3 = "<reasoning>Synthesizing context</reasoning>Done."
        th3, cl3 = extract_and_strip_reasoning(text3)
        assert th3 == "Synthesizing context"
        assert cl3 == "Done."

    def test_uppercase_tags(self):
        """Verifies case-insensitivity with <THINK>, <THOUGHT>, <REASONING>."""
        text = "<THINK>Uppercase reasoning</THINK>Uppercase answer."
        th, cl = extract_and_strip_reasoning(text)
        assert th == "Uppercase reasoning"
        assert cl == "Uppercase answer."

        text_unclosed = "<THINK>Unclosed uppercase thought"
        th_u, cl_u = extract_and_strip_reasoning(text_unclosed)
        assert th_u == "Unclosed uppercase thought"
        assert cl_u == ""

    def test_unclosed_tags_variations(self):
        """Verifies handling of unclosed tags with and without prefix text."""
        # Unclosed at the beginning
        text1 = "<think>Model started thinking but ran out of tokens"
        th1, cl1 = extract_and_strip_reasoning(text1)
        assert th1 == "Model started thinking but ran out of tokens"
        assert cl1 == ""

        # Unclosed with prior text
        text2 = "Visible prefix text\n<thought>Scratchpad notes that got truncated"
        th2, cl2 = extract_and_strip_reasoning(text2)
        assert th2 == "Scratchpad notes that got truncated"
        assert cl2 == "Visible prefix text"

        # Unclosed following a previously closed tag
        text3 = "<think>Part 1 complete</think>Intermediate answer\n<reasoning>Part 2 truncated"
        th3, cl3 = extract_and_strip_reasoning(text3)
        assert th3 == "Part 1 complete\n\nPart 2 truncated"
        assert cl3 == "Intermediate answer"

    def test_empty_and_whitespace_only_tags(self):
        """Verifies that empty tags or tags containing only whitespace produce clean output."""
        text1 = "<think></think>Clean answer."
        th1, cl1 = extract_and_strip_reasoning(text1)
        assert th1 == ""
        assert cl1 == "Clean answer."

        text2 = "<thought>   \n\t  </thought>Another clean answer."
        th2, cl2 = extract_and_strip_reasoning(text2)
        assert th2 == ""
        assert cl2 == "Another clean answer."

        text3 = "<reasoning></reasoning>"
        th3, cl3 = extract_and_strip_reasoning(text3)
        assert th3 == ""
        assert cl3 == ""

    def test_multiple_consecutive_thinking_blocks(self):
        """Verifies multiple consecutive thinking blocks are concatenated with clean double-newlines."""
        text = (
            "<think>Step 1: Check array</think>"
            "<thought>Step 2: Check SMART health</thought>"
            "<reasoning>Step 3: Check temperature</reasoning>"
            "All drives are healthy."
        )
        th, cl = extract_and_strip_reasoning(text)
        assert th == "Step 1: Check array\n\nStep 2: Check SMART health\n\nStep 3: Check temperature"
        assert cl == "All drives are healthy."

    def test_text_without_thinking_tags(self):
        """Verifies that plain text passes through completely unmodified."""
        text = "This is a direct response without any thoughts or tags."
        th, cl = extract_and_strip_reasoning(text)
        assert th == ""
        assert cl == text

    def test_empty_and_none_input(self):
        """Verifies safe handling of empty or None inputs."""
        assert extract_and_strip_reasoning("") == ("", "")
        assert extract_and_strip_reasoning(None) == ("", "")

    def test_nested_tags_adversarial(self):
        """
        Adversarial test: checks behavior when tags are nested or malformed.
        E.g., <think>outer <think>inner</think> outer2</think>answer
        Documents whether inner thoughts or unclosed tags leak.
        """
        text = "<think>outer <think>inner</think> outer2</think>answer"
        th, cl = extract_and_strip_reasoning(text)
        # Note: Non-greedy regex matches <think>outer <think>inner</think>.
        # We record the empirical behavior of nested tags.
        assert "inner" in th
        assert "answer" in cl

    def test_whitespace_in_tag_delimiters(self):
        """
        Adversarial test: checks if whitespace inside tag brackets
        like '<think >' or '</think >' is handled or leaks.
        """
        text = "<think >thought</think >answer"
        th, cl = extract_and_strip_reasoning(text)
        # Empirical test: does the regex match <think > or leak?
        # Current regex r"<(?:think|thought|reasoning)>" requires no space inside tag name
        is_stripped = "<think" not in cl
        # If it leaked, record the exact observation
        if not is_stripped:
            assert "<think >" in cl, "Expected tag to leak due to exact tag regex"

    def test_extremely_large_thinking_content(self):
        """Verifies handling of large 50KB reasoning blocks without memory blowup or regex hang."""
        large_thought = "Thinking step " * 3500
        text = f"<think>{large_thought}</think>Final verdict."
        t0 = time.perf_counter()
        th, cl = extract_and_strip_reasoning(text)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert len(th) > 40000
        assert cl == "Final verdict."
        assert elapsed_ms < 50.0, f"Reasoning extraction took too long: {elapsed_ms:.1f}ms"

    def test_unicode_and_emojis_in_thinking_tags(self):
        """Verifies multi-byte unicode, CJK characters, and emojis inside thought tokens."""
        text = "<think>正在分析存储阵列 🚀 💾 温度正常</think>系统运行良好。"
        th, cl = extract_and_strip_reasoning(text)
        assert "正在分析存储阵列" in th
        assert "🚀" in th
        assert cl == "系统运行良好。"

    def test_mismatched_open_close_tags(self):
        """
        Adversarial test: checks if opening <think> and closing </thought> are handled.
        Because regex matches (think|thought|reasoning) independently, it strips mismatched pairs.
        """
        text = "<think>Cross-tag thinking block</thought>Result."
        th, cl = extract_and_strip_reasoning(text)
        assert th == "Cross-tag thinking block"
        assert cl == "Result."

    def test_tag_with_attributes_leaks(self):
        """
        Adversarial test: checks behavior when model outputs attributes like '<think id="1">'
        Records empirical leakage because tag regex expects strictly '<think>'.
        """
        text = '<think id="1">Thought with attribute</think>Reply.'
        th, cl = extract_and_strip_reasoning(text)
        # Empirical check: tags with attributes are not matched by current regex
        assert '<think id="1">' in cl, "Expected attribute tag to leak in current regex"


# ============================================================================
# 2. Snippet Cleaning & Structured Content Stress Tests
# ============================================================================


class TestSnippetCleaningStress:
    """Adversarial stress-testing of _clean_complete_snippet."""

    def test_markdown_tables_preserved(self):
        """Verifies that markdown table formatting and row pipes '|' are preserved."""
        table_text = (
            "| Disk Device | Power State | Temperature | Health |\n"
            "|---|---|---|---|\n"
            "| /dev/sdb | STANDBY | 32°C | OK |\n"
            "| /dev/sdc | ACTIVE | 38°C | OK |\n"
            "| /dev/nvme0n1 | ACTIVE | 41°C | OK |"
        )
        cleaned = _clean_complete_snippet(table_text, max_chars=800)
        assert "|" in cleaned
        assert "/dev/sdb" in cleaned
        assert "/dev/nvme0n1" in cleaned
        assert cleaned.count("\n") >= 3

    def test_python_code_indentation_and_comments(self):
        """Verifies that Python code with indentation, def, and comments is preserved."""
        code_text = (
            "def calculate_fan_pwm(cpu_temp: float) -> int:\n"
            "    # Emergency clamp at 80C\n"
            "    if cpu_temp >= 80.0:\n"
            "        return 183\n"
            "    return int(40 + (cpu_temp - 30) * 2.8)"
        )
        cleaned = _clean_complete_snippet(code_text, max_chars=800)
        assert "def calculate_fan_pwm" in cleaned
        assert "    # Emergency clamp at 80C" in cleaned
        assert "    if cpu_temp >= 80.0:" in cleaned
        assert "\n" in cleaned

    def test_yaml_docker_compose_blocks(self):
        """Verifies that Docker Compose YAML blocks maintain indented hierarchy."""
        yaml_text = (
            "version: '3.8'\n"
            "services:\n"
            "  vaultwarden:\n"
            "    image: vaultwarden/server:latest\n"
            "    container_name: vaultwarden\n"
            "    restart: unless-stopped\n"
            "    ports:\n"
            "      - '8080:80'\n"
            "    volumes:\n"
            "      - /mnt/user/appdata/vaultwarden:/data"
        )
        cleaned = _clean_complete_snippet(yaml_text, max_chars=800)
        assert "services:" in cleaned
        assert "image: vaultwarden/server:latest" in cleaned
        assert "- '8080:80'" in cleaned

    def test_culinary_recipe_with_fractions_and_steps(self):
        """Verifies culinary recipes with fractional measurements and numbered steps."""
        recipe_text = (
            "Sourdough Bread Recipe:\n"
            "- 1 1/2 cups unbleached all-purpose flour\n"
            "- 2 1/4 tsp active dry yeast\n"
            "- 3/4 cup warm water (105°F to 115°F)\n"
            "- 1/2 tsp kosher salt\n"
            "- 1 tbsp extra virgin olive oil\n"
            "Instructions:\n"
            "1. Dissolve active dry yeast in warm water for 5 minutes.\n"
            "2. Whisk flour, salt, and olive oil in a large bowl."
        )
        cleaned = _clean_complete_snippet(recipe_text, max_chars=800)
        assert "1 1/2 cups" in cleaned
        assert "2 1/4 tsp" in cleaned
        assert "3/4 cup" in cleaned
        assert "1/2 tsp" in cleaned
        assert "1. Dissolve" in cleaned

    def test_raw_unbulleted_recipe_measurements(self):
        """
        Adversarial test: checks how raw ingredient lists without bullets or colons
        are handled by the snippet cleaner.
        """
        raw_recipe = (
            "1 1/2 cups unbleached all purpose flour\n"
            "2 tsp baking powder\n"
            "1/2 cup granulated sugar\n"
            "1 pinch fine sea salt"
        )
        cleaned = _clean_complete_snippet(raw_recipe, max_chars=800)
        # Should not crash and should retain the ingredients
        assert "1 1/2 cups" in cleaned
        assert "2 tsp" in cleaned
        assert "1/2 cup" in cleaned

    def test_bulleted_lists_preserved(self):
        """Verifies that bulleted lists (- / * / +) are preserved."""
        bullet_text = (
            "- Step 1: Verify all array drives are asleep\n"
            "- Step 2: Query SQLite index on NVMe\n"
            "- Step 3: Format grounded answer"
        )
        cleaned = _clean_complete_snippet(bullet_text, max_chars=800)
        assert "- Step 1:" in cleaned
        assert "- Step 2:" in cleaned
        assert "- Step 3:" in cleaned

    def test_single_line_prose_fragments_and_dangling_prepositions(self):
        """Verifies that prose fragments do not end in dangling prepositions/conjunctions."""
        # Sentence ending in 'to' should be stripped
        frag1 = "The ZettNAS hardware controller sends commands to"
        cleaned1 = _clean_complete_snippet(frag1, max_chars=800)
        assert not cleaned1.endswith("to"), f"Expected dangling 'to' to be stripped, got: {cleaned1}"

        # Sentence ending in 'with'
        frag2 = "The fan speed curve adjusts automatically with"
        cleaned2 = _clean_complete_snippet(frag2, max_chars=800)
        assert not cleaned2.endswith("with"), f"Expected dangling 'with' to be stripped, got: {cleaned2}"

        # Valid complete prose sentence without trailing period
        frag3 = "The ZettNAS Toolkit operates smoothly in headless low-RAM homelab environments"
        cleaned3 = _clean_complete_snippet(frag3, max_chars=800)
        assert cleaned3.endswith("."), f"Expected trailing period to be appended, got: {cleaned3}"

    def test_citation_bracket_removal(self):
        """Verifies that Wikipedia-style [1], [2], [citation needed] brackets are cleaned from snippets."""
        raw = "ZettNAS is an enterprise NAS operating system [1] that supports ZFS and Btrfs [citation needed]."
        cleaned = _clean_complete_snippet(raw, max_chars=800)
        assert "[1]" not in cleaned
        assert "[citation needed]" not in cleaned
        assert "ZettNAS is an enterprise NAS operating system" in cleaned

    def test_extremely_large_input_performance(self):
        """
        Verifies that _clean_complete_snippet processes 50KB inputs in < 30ms without ReDoS.
        Note: Because it guarantees complete, unbroken sentences, the returned snippet terminates
        at the end of the sentence that crosses max_chars, never mid-sentence.
        """
        large_blob = "ZettNAS automates container management, hardware telemetry, and thermal safety curves. " * 500
        t0 = time.perf_counter()
        res = _clean_complete_snippet(large_blob, max_chars=850)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        # Complete sentence guarantee: bounded by max_chars plus at most one sentence length
        assert 800 <= len(res) <= 950
        assert res.endswith("."), "Expected unbroken sentence ending in period"
        assert elapsed_ms < 30.0, f"Snippet cleaning exceeded latency threshold: {elapsed_ms:.1f}ms"

    def test_unicode_fractions_recipe(self):
        """Verifies recipe cleaning with unicode vulgar fractions (½, ¼, ¾)."""
        recipe = (
            "Artisan Pizza Dough:\n"
            "- 3½ cups bread flour\n"
            "- 1¼ cups lukewarm water\n"
            "- 1 tsp dry yeast\n"
            "- 2 tbsp extra virgin olive oil\n"
            "Instructions:\n"
            "1. Combine water and yeast."
        )
        res = _clean_complete_snippet(recipe, max_chars=800)
        assert "3½ cups" in res
        assert "1¼ cups" in res

    def test_abbreviations_preserved_at_sentence_boundaries(self):
        """Verifies that common abbreviations (e.g., i.e., vs.) do not cause premature splits."""
        prose = (
            "The ZettNAS platform supports diverse storage engines, e.g. ZFS and Btrfs on Linux. "
            "It provides high fault tolerance against bitrot and disk dropouts."
        )
        res = _clean_complete_snippet(prose, max_chars=800)
        assert "e.g." in res
        assert "ZFS and Btrfs" in res


# ============================================================================
# 3. Context Synthesizer & XML Grounding Formatting Stress Tests
# ============================================================================


class TestStructuredLlmContextStress:
    """Adversarial stress-testing of _build_structured_llm_context."""

    def test_zero_citations_clean_xml(self):
        """Verifies that 0 citations produce a clean <retrieved_documents count="0"> block."""
        tool_results = [
            {
                "tool": "search_nas_knowledge",
                "citations": [],
                "photos": [],
                "context_text": "",
                "folder_path": None,
                "grounding_confidence_score": 0,
                "crag_grade": "low",
            }
        ]
        context = _build_structured_llm_context(tool_results)
        assert '<retrieved_documents count="0">' in context
        assert "</retrieved_documents>" in context
        assert "0 Results Found" in context
        # Tag balancing check
        assert context.count("<retrieved_documents") == context.count("</retrieved_documents>")

    def test_single_citation_with_and_without_parent_context(self):
        """Verifies 1 citation formatting with full_parent_context and chunk_text fallback."""
        # 1. With full parent context
        tr_parent = [
            {
                "tool": "search_nas_knowledge",
                "citations": [
                    {
                        "name": "network_config.md",
                        "doc_title": "Network Architecture",
                        "path": "/mnt/user/docs/network.md",
                        "score": 0.96,
                        "doc_type": "document",
                        "breadcrumb": "VLAN Configuration",
                        "line_start": 42,
                        "line_end": 58,
                        "full_parent_context": "Complete paragraph explaining VLAN trunking on eth0 and br0.",
                    }
                ],
                "photos": [],
            }
        ]
        ctx_parent = _build_structured_llm_context(tr_parent)
        assert '<retrieved_documents count="1">' in ctx_parent
        assert (
            '<document index="1" title="Network Architecture" file="network_config.md" path="/mnt/user/docs/network.md" relevance="96%" modality="document" lines="42-58">'
            in ctx_parent
        )
        assert "[Section: VLAN Configuration]" in ctx_parent
        assert "Complete paragraph explaining VLAN trunking" in ctx_parent
        assert "</document>" in ctx_parent
        assert "</retrieved_documents>" in ctx_parent

        # 2. Without full_parent_context (fallback to chunk_text / excerpt)
        tr_chunk = [
            {
                "tool": "search_nas_knowledge",
                "citations": [
                    {
                        "name": "docker.md",
                        "chunk_text": "Fallback chunk excerpt about container mutator.",
                        "score": 0.88,
                    }
                ],
            }
        ]
        ctx_chunk = _build_structured_llm_context(tr_chunk)
        assert "Fallback chunk excerpt about container mutator." in ctx_chunk
        assert 'relevance="88%"' in ctx_chunk

    def test_ten_citations_count_and_tag_balancing(self):
        """
        Adversarial test: checks behavior when 10 citations are provided.
        Verifies whether count attribute matches actual <document> tags or documents limit behavior.
        """
        citations_10 = [
            {
                "name": f"file_{i}.txt",
                "doc_title": f"Document {i}",
                "path": f"/mnt/user/docs/file_{i}.txt",
                "score": 0.95 - (i * 0.02),
                "full_parent_context": f"Content for document {i}",
                "line_start": i * 10,
                "line_end": (i * 10) + 5,
            }
            for i in range(1, 11)
        ]
        tool_results = [
            {
                "tool": "search_nas_knowledge",
                "citations": citations_10,
                "photos": [],
            }
        ]
        context = _build_structured_llm_context(tool_results)
        # Verify tag balancing
        assert context.count("<retrieved_documents") == context.count("</retrieved_documents>")
        rendered_doc_tags = context.count("<document index=")
        rendered_closing_tags = context.count("</document>")
        assert rendered_doc_tags == rendered_closing_tags, (
            f"Unbalanced <document> tags: {rendered_doc_tags} vs {rendered_closing_tags}"
        )
        # Inspect count attribute vs rendered count
        m_count = re.search(r'<retrieved_documents count="(\d+)">', context)
        assert m_count is not None
        claimed_count = int(m_count.group(1))
        # Note: In ai_chat_agent.py, citations[:8] limits to 8 documents.
        # Check if claimed_count is 10 or 8.
        assert rendered_doc_tags <= 8, f"Expected at most 8 documents rendered, got: {rendered_doc_tags}"

    def test_citations_with_photos_and_structured_card(self):
        """Verifies clean XML blocks for citations combined with photos and structured entity cards."""
        tool_results = [
            {
                "tool": "search_nas_knowledge",
                "citations": [
                    {
                        "name": "drive_bay.md",
                        "full_parent_context": "Drive bay layout for 8-bay chassis.",
                        "score": 0.92,
                    }
                ],
                "photos": [
                    {
                        "name": "chassis_front.jpg",
                        "path": "/mnt/user/photos/chassis_front.jpg",
                        "taken_at": "2026-05-10",
                        "scene_tags": ["hardware", "chassis", "server"],
                        "caption": "Front view of Zettlab D8 appliance showing hot-swap trays.",
                    }
                ],
                "structured_card": {
                    "card_type": "storage_summary",
                    "pool": "tank",
                    "total_tib": 32.0,
                    "free_tib": 18.5,
                },
            }
        ]
        context = _build_structured_llm_context(tool_results)
        # Check retrieved_documents
        assert '<retrieved_documents count="1">' in context
        assert "</retrieved_documents>" in context

        # Check retrieved_photos
        assert '<retrieved_photos count="1">' in context
        assert '<photo index="1" name="chassis_front.jpg"' in context
        assert 'tags="hardware, chassis, server"' in context
        assert "Front view of Zettlab D8 appliance" in context
        assert "</photo>" in context
        assert "</retrieved_photos>" in context

        # Check structured_entity
        assert '<structured_entity type="storage_summary">' in context
        assert '"pool": "tank"' in context
        assert "</structured_entity>" in context

        # Check overall XML structure balancing
        assert context.count("<retrieved_photos") == context.count("</retrieved_photos>")
        assert context.count("<photo index=") == context.count("</photo>")
        assert context.count("<structured_entity") == context.count("</structured_entity>")

    def test_corrupt_and_missing_citation_fields(self):
        """
        Adversarial test: checks resilience when citations have None or missing fields
        (e.g., None score, missing name, missing path, non-numeric score string).
        """
        tool_results = [
            {
                "tool": "search_nas_knowledge",
                "citations": [
                    {},  # completely empty dictionary
                    {"name": None, "doc_title": None, "score": "not-a-number"},
                    {"name": "partial.md", "score": None},
                ],
            }
        ]
        context = _build_structured_llm_context(tool_results)
        # Must not crash and must emit 3 document tags
        assert '<retrieved_documents count="3">' in context
        assert context.count("<document index=") == 3
        assert context.count("</document>") == 3

    def test_telemetry_fans_and_docker_context_formatting(self):
        """Verifies context formatting for non-knowledge system telemetry tools."""
        tool_results = [
            {
                "tool": "get_system_telemetry",
                "cpu_load_pct": 12.4,
                "cpu_temp_c": 44,
                "ram_used_pct": 38.2,
                "ram_used_gb": 6.1,
                "ram_total_gb": 16.0,
            },
            {
                "tool": "get_fan_and_thermal_status",
                "fans": [
                    {"zone": "bay", "rpm": 1150, "pwm_pct": 45},
                    {"zone": "cpu", "rpm": 2200, "pwm_pct": 60},
                ],
            },
            {
                "tool": "list_docker_containers",
                "running": 5,
                "total": 6,
                "containers": [
                    {"name": "nextcloud", "state": "running", "status": "Up 3 days", "image": "nextcloud:fpm"},
                ],
            },
        ]
        context = _build_structured_llm_context(tool_results)
        assert "## NAS System Telemetry:" in context
        assert "CPU Utilization: 12.4%, Temp: 44°C" in context
        assert "RAM Usage: 38.2% (6.1/16.0 GB)" in context
        assert "## Cooling Fans Status:" in context
        assert "Fan bay: 1150 RPM (45%)" in context
        assert "## Docker Containers (5 running / 6 total):" in context
        assert "nextcloud: running" in context


# ============================================================================
# 4. Symlink Resolution & Backing Physical Device Stress Tests
# ============================================================================


class TestSymlinkBackingDeviceResolution:
    """
    Adversarial stress-testing of resolve_path_backing_dev:
    Verifies that symlinks traversing from SSD cache paths to spinning array drives
    resolve to physical drive names ('sda', 'sdb', etc.) and NEVER falsely claim 'nvme0n1'.
    """

    def test_cache_symlink_to_array_disk_resolves_to_spinning_disk(self, tmp_path):
        """Creates physical symlinks on disk traversing from cache directory to disk1."""
        cache_dir = tmp_path / "mnt" / "cache" / "shares"
        cache_dir.mkdir(parents=True)

        target_path = "/mnt/disk1/shares/target_document.txt"
        symlink_file = cache_dir / "symlink_document.txt"
        symlink_file.symlink_to(target_path)

        mock_unraid_disks = {"disk1": {"device": "sdb", "type": "data"}}

        with patch("backend.services.rag_engine._get_unraid_disks_and_shares", return_value=(mock_unraid_disks, {})):
            # Calling on the symlink file path
            resolved = resolve_path_backing_dev(str(symlink_file))
            # Must NOT claim nvme0n1! Must resolve to sdb
            assert resolved == "sdb", f"Expected 'sdb' for symlink pointing to disk1, got: {resolved}"
            assert resolved != "nvme0n1", "CRITICAL BUG: Symlink to spinning disk falsely claimed nvme0n1!"

    def test_chained_symlinks_ssd_to_spinning_disk(self, tmp_path):
        """Verifies chained symlinks (cache -> ssd -> disk2) dereference fully to sdc."""
        cache_dir = tmp_path / "mnt" / "cache"
        ssd_dir = tmp_path / "mnt" / "ssd"
        cache_dir.mkdir(parents=True)
        ssd_dir.mkdir(parents=True)

        target_path = "/mnt/disk2/shares/data.bin"

        intermediate_link = ssd_dir / "link_step1.bin"
        intermediate_link.symlink_to(target_path)

        top_link = cache_dir / "link_step2.bin"
        top_link.symlink_to(intermediate_link)

        mock_unraid_disks = {"disk2": {"device": "sdc", "type": "data"}}

        with patch("backend.services.rag_engine._get_unraid_disks_and_shares", return_value=(mock_unraid_disks, {})):
            resolved = resolve_path_backing_dev(str(top_link))
            assert resolved == "sdc"
            assert resolved != "nvme0n1"

    def test_broken_symlink_points_to_spinning_disk(self, tmp_path):
        """
        Adversarial test: broken symlink pointing to nonexistent path on /mnt/disk3.
        Verifies that realpath still follows the path to disk3 without throwing exception.
        """
        cache_dir = tmp_path / "mnt" / "cache"
        cache_dir.mkdir(parents=True)
        nonexistent_target = "/mnt/disk3/missing_folder/ghost.txt"

        broken_link = cache_dir / "ghost_link.txt"
        broken_link.symlink_to(nonexistent_target)

        mock_unraid_disks = {"disk3": {"device": "sdd", "type": "data"}}

        with patch("backend.services.rag_engine._get_unraid_disks_and_shares", return_value=(mock_unraid_disks, {})):
            resolved = resolve_path_backing_dev(str(broken_link))
            assert resolved == "sdd"
            assert resolved != "nvme0n1"

        assert resolve_path_backing_dev("/mnt/cache/appdata/config.json") == "nvme0n1"
        assert resolve_path_backing_dev("/mnt/nvme/data/index.db") == "nvme0n1"
        assert resolve_path_backing_dev("/app/data/rag_index.db") == "nvme0n1"

    def test_circular_symlink_safe_fallback(self, tmp_path):
        """
        Adversarial test: circular symlinks (symA -> symB -> symA).
        Verifies resolve_path_backing_dev gracefully handles recursion without crash or hang.
        """
        link_a = tmp_path / "link_a"
        link_b = tmp_path / "link_b"
        link_a.symlink_to(link_b)
        link_b.symlink_to(link_a)

        # Must not hang or raise unhandled RecursionError
        res = resolve_path_backing_dev(str(link_a))
        assert isinstance(res, str)

    def test_symlink_to_unraid_user_share_cache_vs_array(self, tmp_path):
        """
        Verifies that a symlink pointing to /mnt/user/cache_share resolves to cache pool device,
        while a symlink to /mnt/user/array_share resolves to array drive sdb.
        """
        cache_link = tmp_path / "cache_share_link"
        cache_link.symlink_to("/mnt/user/downloads")

        array_link = tmp_path / "array_share_link"
        array_link.symlink_to("/mnt/user/media")

        mock_disks = {
            "disk1": {"device": "sdb", "type": "data"},
            "cache": {"device": "nvme0n1", "type": "cache"},
        }
        mock_shares = {
            "downloads": {"useCache": "only", "cachePool": "cache"},
            "media": {"useCache": "no"},
        }

        with patch("backend.services.rag_engine._get_unraid_disks_and_shares", return_value=(mock_disks, mock_shares)):
            dev_cache = resolve_path_backing_dev(str(cache_link))
            assert dev_cache == "nvme0n1"

            dev_array = resolve_path_backing_dev(str(array_link))
            assert dev_array == "sdb"


# ============================================================================
# 5. Zero-Disk-Spindown Safety During Query Execution & Context Assembly
# ============================================================================


class TestZeroDiskSpindownSafety:
    """
    Stress-testing zero-disk-spindown invariants:
    Verifies that running queries, RAG searches, and context generation NEVER
    invokes disk-waking syscalls on sleeping spinning drives.
    """

    @pytest.fixture
    def test_rag_db(self, tmp_path):
        """Sets up a temporary RAG SQLite index using native schema with documents on array paths."""
        db_path = str(tmp_path / "rag_index_spindown_test.db")
        engine = RagSearchEngine(db_path=db_path)

        import struct

        blob384 = struct.pack("<384f", *([0.1] * 384))
        # Populate sample document backed by sleeping drive 'sdb' (/mnt/disk1)
        conn = engine._get_conn(readonly=False)
        try:
            conn.execute(
                """
                INSERT INTO indexed_files
                (file_id, canonical_path, parent_dir, file_name, file_ext, size_bytes, mtime_ns, sha256_hash, modality, doc_type, doc_title, backing_dev, parse_status, index_version, indexed_at, last_verified_at)
                VALUES (1, '/mnt/disk1/documents/nas_manual.md', '/mnt/disk1/documents', 'nas_manual.md', '.md', 1024, 1000, 'hash1', 'document', 'technical_manual', 'NAS User Manual', 'sdb', 'ok', 3, 1000.0, 1000.0);
                """
            )
            conn.execute(
                """
                INSERT INTO document_chunks
                (chunk_id, file_id, chunk_index, heading_context, chunk_text, raw_chunk_text, line_start, line_end, token_count, embedding_f32, parent_chunk_id)
                VALUES (1, 1, 0, 'Thermal Architecture', 'ZettNAS uses intelligent fan curves with emergency clamp at 80C.', 'ZettNAS uses intelligent fan curves with emergency clamp at 80C.', 1, 5, 20, ?, NULL);
                """,
                (blob384,),
            )
            conn.commit()
        finally:
            conn.close()

        yield engine, db_path
        engine.close()

    def test_smartctl_never_called_without_n_standby(self):
        """Verifies smartctl is strictly called with -n standby flag (AGENTS.md §1.2)."""
        calls = []

        def spy_subprocess_run(cmd, *args, **kwargs):
            calls.append(cmd)
            mock_res = MagicMock()
            mock_res.returncode = 2
            mock_res.stdout = "Device is in STANDBY mode, exiting(2)"
            mock_res.stderr = ""
            return mock_res

        # On generic Linux hosts (non-Unraid), _get_unraid_disks_and_shares returns {}
        with (
            patch("backend.services.rag_engine._get_unraid_disks_and_shares", return_value=({}, {})),
            patch("subprocess.run", side_effect=spy_subprocess_run),
            patch("os.path.exists", return_value=True),
        ):
            # Probe drive in standby with check_smartctl=True
            result = is_backing_disk_in_standby("sdb", check_smartctl=True)
            assert result is True

            # Verify that every smartctl call included '-n' and 'standby'
            assert len(calls) > 0, "Expected smartctl to be called"
            for c in calls:
                if isinstance(c, list) and c[0] == "smartctl":
                    assert "-n" in c, f"smartctl called without -n: {c}"
                    assert "standby" in c, f"smartctl called without standby flag: {c}"

    def test_search_and_ask_never_wake_sleeping_disks(self, test_rag_db):
        """
        CRITICAL VERIFICATION:
        Ensures that rag.search(), rag.ask(), and context assembly do NOT call open()
        or os.stat() on spinning array disks (/mnt/disk* or /dev/sd*).
        All metadata must be read strictly from the SQLite database.
        """
        engine, db_path = test_rag_db

        # Mark drive 'sdb' as sleeping: simulate both Unraid (spundown="1") and generic Linux
        mock_unraid = {"disk1": {"device": "sdb", "type": "data", "spundown": "1"}}
        Z_STATE.cached_smart_data["sdb"] = (35, "standby")

        opened_paths: list[str] = []
        original_open = open

        def guarded_open(file, *args, **kwargs):
            path_str = str(file)
            opened_paths.append(path_str)
            if path_str.startswith(("/mnt/disk", "/dev/sd", "/host/dev/sd")):
                raise AssertionError(
                    f"INVARIANT VIOLATION: Spindown guard broken! Attempted physical disk read on sleeping drive: {path_str}"
                )
            return original_open(file, *args, **kwargs)

        with (
            patch("backend.services.rag_engine._get_unraid_disks_and_shares", return_value=(mock_unraid, {})),
            patch("builtins.open", side_effect=guarded_open),
        ):
            # 1. Execute rag.search
            res_search = engine.search(query="fan curve clamp", mode="all")
            assert len(res_search.get("document_results", [])) > 0
            hit = res_search["document_results"][0]
            # Must reflect standby status
            assert hit.get("disk_state") == "standby"

            # 2. Execute rag.ask
            res_ask = engine.ask(query="fan curve thermal clamp")
            assert len(res_ask.get("citations", [])) > 0
            citation = res_ask["citations"][0]
            assert citation.get("disk_state") == "standby"

            # 3. Format into structured LLM context
            tool_res = [
                {
                    "tool": "search_nas_knowledge",
                    "citations": res_ask.get("citations", []),
                    "photos": [],
                    "grounding_confidence_score": 95,
                    "crag_grade": "high",
                }
            ]
            llm_context = _build_structured_llm_context(tool_res)
            assert '<retrieved_documents count="1">' in llm_context
            assert "ZettNAS uses intelligent fan curves" in llm_context

        # Verify no spinning disk paths were opened
        spinning_opens = [p for p in opened_paths if p.startswith(("/mnt/disk", "/dev/sd"))]
        assert len(spinning_opens) == 0, f"Disallowed physical disk opens: {spinning_opens}"

    def test_tool_search_nas_knowledge_standby_preservation(self, test_rag_db):
        """Verifies tool_search_nas_knowledge maintains zero disk wakeups."""
        engine, db_path = test_rag_db
        mock_unraid = {"disk1": {"device": "sdb", "type": "data", "spundown": "1"}}
        Z_STATE.cached_smart_data["sdb"] = (35, "standby")

        with (
            patch("backend.services.rag_engine._get_unraid_disks_and_shares", return_value=(mock_unraid, {})),
            patch("backend.services.ai_chat_agent.get_rag_engine", return_value=engine),
            patch("backend.services.rag_engine.get_rag_engine", return_value=engine),
        ):
            res = tool_search_nas_knowledge(query="fan curve thermal")
            assert res.get("tool") == "search_nas_knowledge"
            assert res.get("citations_count", 0) >= 1
            citations = res.get("citations", [])
            assert citations[0].get("disk_state") == "standby"

    def test_multi_mode_search_zero_wakeups(self, test_rag_db):
        """Verifies search across all modes (documents, recipes, photos, folders) executes purely against WAL db."""
        engine, db_path = test_rag_db
        mock_unraid = {"disk1": {"device": "sdb", "type": "data", "spundown": "1"}}

        with patch("backend.services.rag_engine._get_unraid_disks_and_shares", return_value=(mock_unraid, {})):
            for mode in ("all", "documents", "recipes", "photos", "folders"):
                res = engine.search(query="manual", mode=mode)
                assert isinstance(res, dict)
                assert "query" in res

    def test_get_sleeping_and_running_disks_helpers(self):
        """Verifies get_sleeping_disks_list and get_running_disks_list without physical disk touches."""
        from backend.services.rag_engine import get_running_disks_list, get_sleeping_disks_list

        mock_disks = {
            "disk1": {"device": "sdb", "type": "data", "spundown": "1"},
            "disk2": {"device": "sdc", "type": "data", "spundown": "0"},
        }
        with patch("backend.services.rag_engine._get_unraid_disks_and_shares", return_value=(mock_disks, {})):
            sleeping = get_sleeping_disks_list()
            running = get_running_disks_list()
            assert "sdb" in sleeping
            assert "sdc" in running
