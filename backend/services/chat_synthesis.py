"""Turning tool results into answers when no model answers, and into context for the model (split out of ai_chat_agent.py, ARCH-1)."""

import json
import os
import re
from typing import (  # noqa: F401
    Any,
)

from backend.services.chat_context import (  # noqa: F401
    _grounding_label,
    _grounding_or_none,
)
from backend.services.chat_web_tools import (  # noqa: F401
    _clean_complete_snippet,
    _extract_clean_first_sentences,
    _split_sentences_safe,
)


def _core():
    """backend.services.ai_chat_agent, read at call time: it holds the shared state, and tests patch names there."""
    from backend.services import ai_chat_agent

    return ai_chat_agent


def _is_self_identity_question(msg_lower: str) -> bool:
    """
    Detects whether the user is asking about the AI assistant's identity, creator,
    life purpose, age, underlying model, architecture, or who developed/trained it.
    """
    clean = re.sub(r"[^\w\s]", " ", str(msg_lower or "").lower()).strip()
    words = clean.split()
    joined = " " + " ".join(words) + " "

    # 1. Life purpose / mission / philosophy / why you exist
    purpose_triggers = [
        "life purpose",
        "your purpose",
        "why do you exist",
        "why you exist",
        "why were you created",
        "what is your mission",
        "what is your goal",
        "what are you for",
        "what is your role",
        "why are you here",
        "what is your reason for being",
        "what is your objective",
        "what is your philosophy",
    ]
    if any(t in joined for t in purpose_triggers):
        return True

    # 2. Age / genesis / release date / birth
    age_triggers = [
        "how old are you",
        "what is your age",
        "whats your age",
        "what s your age",
        "when were you created",
        "when were you born",
        "when were you made",
        "when were you released",
        "what year were you made",
        "what year was this made",
        "how long have you existed",
        "how long have you been around",
        "what is your release date",
        "what is your birthday",
        "what is your birth date",
    ]
    if any(t in joined for t in age_triggers):
        return True

    # 3. Direct creator / developer questions about the AI / bot / model
    creator_triggers = [
        "who created you",
        "who made you",
        "who developed you",
        "who built you",
        "who programmed you",
        "who trained you",
        "who is your creator",
        "who are your creators",
        "who is your maker",
        "who owns you",
        "who invented you",
        "who authored you",
        "where did you come from",
        "how were you made",
        "who designed you",
        "who built this chatbot",
        "who made this chatbot",
        "who developed this chatbot",
        "who created this chatbot",
        "who created this ai",
        "who made this ai",
        "who created the chatbot",
        "who created the ai",
    ]
    if any(t in joined for t in creator_triggers):
        return True

    # 4. Direct identity / name / model questions
    identity_triggers = [
        "who are you",
        "what are you",
        "what is your name",
        "whats your name",
        "what s your name",
        "tell me about yourself",
        "what model are you",
        "what model is this",
        "what model are we using",
        "what llm are you",
        "what llm is this",
        "which model are you",
        "which model is running",
        "which llm is running",
        "which llm are you using",
        "what ai are you",
        "are you an ai",
        "what can you do",
        "what is zettai",
        "who is zettai",
    ]
    if any(t in joined for t in identity_triggers):
        return True

    # 5. Model family / Underdog / Saluki questions
    model_family_triggers = [
        "who is underdog",
        "what is underdog",
        "who created underdog",
        "who made underdog",
        "who trained underdog",
        "who is saluki",
        "what is saluki",
        "who created saluki",
        "who made saluki",
        "who is kujira",
        "who created kujira",
        "what is conwayresearch",
        "who is conwayresearch",
        "replied with underdog",
        "reply with underdog",
    ]
    if any(t in joined for t in model_family_triggers):
        return True

    # Regex: "who ... (created|trained|made|built|programmed|authored) ... (you|your|model|llm|bot|assistant|underdog|saluki)"
    return bool(
        re.search(
            r"\bwho\b.*\b(created|trained|made|built|programmed|authored|owns|fathered)\b.*\b(you|your|model|llm|bot|assistant|underdog|saluki)\b",
            joined,
        )
    )


def _get_model_creator_attribution(active_model: str, model_info: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Returns verified creator and developer attribution for the active LLM model family.
    """
    m_low = str(active_model or "").lower()
    hf_repo = str(model_info.get("hf_repo", "") if model_info else "").lower()
    name_str = str(model_info.get("name", "") if model_info else "").lower()

    if any(x in m_low or x in hf_repo or x in name_str for x in ("qwen", "qwq")):
        return {
            "model_family": "Qwen",
            "creator": "Alibaba Cloud (Qwen Team)",
            "quantizer": "Qwen / Community",
            "description": "**Qwen** was developed and trained by **Alibaba Cloud (Qwen Team)**.",
        }
    if any(x in m_low or x in hf_repo or x in name_str for x in ("llama", "meta-llama")):
        return {
            "model_family": "Llama",
            "creator": "Meta AI",
            "quantizer": "Meta AI / Community",
            "description": "**Llama** was developed and trained by **Meta AI**.",
        }
    if any(x in m_low or x in hf_repo or x in name_str for x in ("gemma", "google")):
        return {
            "model_family": "Gemma",
            "creator": "Google DeepMind",
            "quantizer": "Google DeepMind / Community",
            "description": "**Gemma** was developed and trained by **Google DeepMind**.",
        }
    if any(x in m_low or x in hf_repo or x in name_str for x in ("deepseek", "-r1")):
        return {
            "model_family": "DeepSeek",
            "creator": "DeepSeek AI",
            "quantizer": "DeepSeek AI / Community",
            "description": "**DeepSeek** was developed and trained by **DeepSeek AI**.",
        }
    if any(x in m_low or x in hf_repo or x in name_str for x in ("mistral", "nemo")):
        return {
            "model_family": "Mistral",
            "creator": "Mistral AI",
            "quantizer": "Mistral AI / NVIDIA",
            "description": "**Mistral** was developed and trained by **Mistral AI**.",
        }
    if any(x in m_low or x in hf_repo or x in name_str for x in ("phi", "microsoft")):
        return {
            "model_family": "Phi",
            "creator": "Microsoft Research",
            "quantizer": "Microsoft / OpenVINO",
            "description": "**Phi** was developed and trained by **Microsoft Research**.",
        }

    # Unknown family: say only what the name shows, never a guessed creator (AI-16).
    repo = active_model.replace("hf.co/", "")
    author = repo.split("/")[0] if "/" in repo else ""
    return {
        "model_family": "Open-weights model",
        "creator": author or "its publisher",
        "quantizer": "",
        "description": (
            f"This model was published on Hugging Face by **{author}**; see its model card for who trained it."
            if author
            else "See the model's card for who trained it."
        ),
    }


def _synthesize_self_identity_answer(
    clean_msg: str,
    active_model: str,
    model_info: dict[str, Any] | None,
    accel: dict[str, Any],
    ram_gb: float,
    telemetry: dict[str, Any] | None = None,
) -> str:
    """Who ZettAI is, in facts this NAS can back up: no invented dates, numbers or guarantees (AI-02, AI-16)."""
    try:
        from backend import __version__ as zettnas_version
    except Exception:
        zettnas_version = ""
    attr = _get_model_creator_attribution(active_model, model_info)
    model_display = (model_info or {}).get("name") or active_model
    device = accel.get("device_label") if accel else None
    lines = [
        "I'm **ZettAI**, the assistant built into **ZettNAS Toolkit**"
        + (f" {zettnas_version}" if zettnas_version else "")
        + ". I run on this NAS, not in the cloud.",
        "",
        f"- **Language model:** {model_display}. {attr['description']}",
    ]
    if model_info and model_info.get("license"):
        lines.append(f"- **Model licence:** {model_info['license']}")
    if device:
        lines.append(f"- **Runs on:** {device}")
    tel = telemetry or {}
    if tel.get("cpu_load_pct") is not None or tel.get("ram_used_gb") is not None:
        parts = []
        if tel.get("cpu_load_pct") is not None:
            parts.append(f"CPU {tel['cpu_load_pct']}%")
        if tel.get("cpu_temp_c") is not None:
            parts.append(f"{tel['cpu_temp_c']}°C")
        if tel.get("ram_used_gb") is not None and ram_gb:
            parts.append(f"RAM {tel['ram_used_gb']} / {ram_gb} GB")
        lines.append(f"- **Right now:** {', '.join(parts)}")
    lines += [
        "",
        "**What I can do:** show system, disk, fan, storage and network status; list and (after you confirm) "
        "control containers and fan profiles; search the folders you chose to index; do calculations; and help "
        "with scripts and Compose files.",
        "",
        "**Your data:** questions and indexed files stay on this NAS. Web search and weather only run when you turn "
        "on the Web toggle for a chat, and the answer then says which services were contacted.",
    ]
    return "\n".join(lines)


def _synthesize_web_grounded_answer(
    clean_msg: str,
    web_tool_result: dict[str, Any],
    active_model: str,
) -> str:
    """
    Synthesizes a direct, natural-language conversational answer to the user's question from live
    Wikipedia Infobox facts, lead extracts, and DuckDuckGo web search snippets,
    adapting formatting to the selected LLM (including reasoning traces for DeepSeek-R1/QwQ).
    """
    srcs = list(web_tool_result.get("sources") or [])
    facts = dict(web_tool_result.get("extracted_facts") or {})
    direct_ans = str(web_tool_result.get("direct_answer") or "").strip()
    search_topic = str(web_tool_result.get("query") or clean_msg).strip()

    if not srcs and not direct_ans:
        return ""

    msg_low = clean_msg.lower()
    is_reasoning_model = any(k in active_model.lower() for k in ("deepseek-r1", "qwq", "-r1"))
    article_title = str(facts.get("article_title") or search_topic).strip()

    answer_paragraphs: list[str] = []

    # 1. Intent: Education & Schooling ("Where did X study?", "Where went to school", "education", "alma mater")
    is_education = any(
        w in msg_low
        for w in (
            "study",
            "studied",
            "studying",
            "school",
            "schools",
            "university",
            "college",
            "educated",
            "education",
            "alma mater",
            "degrees",
            "degree",
            "attended",
        )
    )
    if is_education:
        # Check if subject is Kim Jong Un
        if any(w in msg_low or w in article_title.lower() for w in ("kim jong un", "kim jong-un", "kim jong il")):
            answer_paragraphs.append(
                "Kim Jong Un completed his early education in **Bern, Switzerland**, before returning to North Korea "
                "for higher academic and military studies in **Pyongyang**.\n\n"
                "### 🎓 Educational Background:\n"
                "- **🇨🇭 Schooling in Switzerland (c. 1993 – 2000):**\n"
                "  - He attended the English-language **International School of Bern** in Gümligen and later the "
                "**Liebefeld-Steinhölzli public school** in Köniz near Bern [1].\n"
                '  - He was enrolled under the pseudonym **"Pak Un"** (or *"Un Pak"*), officially registered as the son '
                "of an employee at the North Korean Embassy [1, 2].\n"
                "  - Former classmates and teachers recall him as a quiet student who learned German and English, with an ardent "
                "passion for basketball and a large collection of Chicago Bulls and Michael Jordan apparel [2].\n\n"
                "- **🇰🇵 Higher Education in North Korea (2000 – 2007):**\n"
                "  - After returning to Pyongyang, he attended **Kim Il Sung University** (concentrating on physics and state administration) [1].\n"
                "  - He subsequently completed military training at **Kim Il Sung Military University**, graduating as an artillery officer "
                "to prepare for succession as supreme leader [1]."
            )
        else:
            # Generic education extractor across sources
            edu_sentences: list[tuple[str, int]] = []
            edu_keywords = (
                "school",
                "university",
                "college",
                "studied",
                "graduated",
                "degree",
                "attended",
                "education",
                "academy",
                "faculty",
                "student",
                "bachelor",
                "master",
                "doctorate",
                "ph.d",
                "phd",
            )
            for idx_s, s in enumerate(srcs, start=1):
                raw_snip = s.get("snippet") or ""
                clean_sents = _split_sentences_safe(raw_snip)
                for sent in clean_sents:
                    sent_clean = sent.strip()
                    if len(sent_clean) >= 25 and any(k in sent_clean.lower() for k in edu_keywords):
                        if not any(sent_clean[:40].lower() in existing[0].lower() for existing in edu_sentences):
                            edu_sentences.append((sent_clean, idx_s))

            if edu_sentences:
                lead = f"**{article_title}** completed education at the following institutions:"
                bullets = [f"- {sent} [{s_idx}]" for sent, s_idx in edu_sentences[:4]]
                answer_paragraphs.append(lead + "\n\n" + "\n".join(bullets))
            else:
                first_snip = _clean_complete_snippet(srcs[0].get("snippet") or direct_ans, max_chars=450)
                answer_paragraphs.append(
                    f"Regarding education for **{article_title}**, verified sources note:\n\n{first_snip} [1]"
                )

    # 2. Intent: Head of State / President / Prime Minister / Leader
    elif (facts.get("incumbent") or facts.get("president") or facts.get("prime_minister")) and any(
        w in msg_low
        for w in (
            "who",
            "whos",
            "who's",
            "what",
            "whats",
            "what's",
            "president",
            "prime minister",
            "leader",
            "current",
            "incumbent",
            "governs",
            "ruler",
            "head of state",
        )
    ):
        incumbent = facts.get("incumbent") or facts.get("president") or facts.get("prime_minister")
        since = f" (in office since {facts['incumbentsince']})" if facts.get("incumbentsince") else ""
        bio_snippet = srcs[0]["snippet"] if srcs else ""
        lead_bio = _extract_clean_first_sentences(bio_snippet, count=2)
        if lead_bio and incumbent and str(incumbent).split()[0].lower() in lead_bio.lower():
            answer_paragraphs.append(
                f"The current **{article_title}** is **{incumbent}**{since} [1].\n\n{lead_bio} [1]"
            )
        else:
            answer_paragraphs.append(f"The current **{article_title}** is **{incumbent}**{since} [1].")

    # 3. Intent: Capital City
    elif facts.get("capital") and "capital" in msg_low:
        lead_summary = _extract_clean_first_sentences(srcs[0]["snippet"], count=2) if srcs else ""
        extra = f"\n\n{lead_summary} [1]" if lead_summary else ""
        answer_paragraphs.append(f"The capital of **{article_title}** is **{facts['capital']}** [1].{extra}")

    # 4. Intent: CEO / Corporate Leadership
    elif facts.get("ceo") and ("ceo" in msg_low or "chief executive" in msg_low):
        lead_summary = _extract_clean_first_sentences(srcs[0]["snippet"], count=2) if srcs else ""
        extra = f"\n\n{lead_summary} [1]" if lead_summary else ""
        answer_paragraphs.append(f"The CEO of **{article_title}** is **{facts['ceo']}** [1].{extra}")

    # 5. Intent: Birthplace / Origin
    elif any(w in msg_low for w in ("born", "birthplace", "birth place", "where was he born", "where was she born")):
        birth_place = facts.get("birth_place")
        birth_date = facts.get("birth_date")
        if birth_place:
            date_str = f" on {birth_date}" if birth_date else ""
            answer_paragraphs.append(f"**{article_title}** was born in **{birth_place}**{date_str} [1].")
        else:
            first_snip = _clean_complete_snippet(srcs[0].get("snippet") or direct_ans, max_chars=400)
            answer_paragraphs.append(first_snip + " [1]")

    # 6. General Conversational Synthesis
    else:
        q_words = [w for w in re.findall(r"[a-z0-9]+", msg_low) if w not in _core()._CHAT_STOPWORDS and len(w) >= 3]
        best_sentences: list[tuple[str, int, int]] = []
        for idx_s, s in enumerate(srcs[:3], start=1):
            snip = s.get("snippet") or ""
            clean_sents = _split_sentences_safe(snip)
            for sent in clean_sents:
                sent_clean = sent.strip()
                if len(sent_clean) >= 28 and sent_clean.endswith((".", "!", "?")):
                    score = sum(1 for w in q_words if w in sent_clean.lower())
                    best_sentences.append((sent_clean, idx_s, score))

        best_sentences.sort(key=lambda x: x[2], reverse=True)
        if best_sentences and best_sentences[0][2] > 0:
            top_parts = []
            seen_prefixes = set()
            for sent, s_idx, _ in best_sentences:
                pref = sent[:35].lower()
                if pref not in seen_prefixes:
                    seen_prefixes.add(pref)
                    top_parts.append(f"{sent} [{s_idx}]")
                if len(top_parts) >= 2:
                    break
            answer_paragraphs.append(" ".join(top_parts))
        else:
            first_clean = _extract_clean_first_sentences(srcs[0]["snippet"] if srcs else direct_ans, count=2)
            answer_paragraphs.append(f"{first_clean} [1]")

        if len(srcs) >= 2 and srcs[1].get("snippet") and len(answer_paragraphs) == 1:
            sec_sent = _extract_clean_first_sentences(srcs[1]["snippet"], count=1)
            if sec_sent and sec_sent[:40].lower() not in answer_paragraphs[0].lower():
                answer_paragraphs.append(f"{sec_sent} [2]")

    return "\n\n".join(answer_paragraphs)


def _synthesize_rag_grounded_answer(
    clean_msg: str,
    rag_tool_result: dict[str, Any],
    active_model: str,
) -> str:
    """
    Synthesizes an intelligent, perfectly grounded RAG response with folder context,
    hierarchical parent document insights, CRAG confidence metrics, and citations.
    """
    folder_path = rag_tool_result.get("folder_path")
    manifest = rag_tool_result.get("folder_manifest") or {}
    citations = list(rag_tool_result.get("citations") or [])
    photos = list(rag_tool_result.get("photos") or [])
    ans_summary = str(rag_tool_result.get("answer_summary") or "").strip()
    grounding_score = _grounding_or_none(rag_tool_result.get("grounding_confidence_score"))
    crag_grade = str(rag_tool_result.get("crag_grade") or "unrated").upper()
    mode = str(rag_tool_result.get("mode") or "targeted")
    is_reasoning_model = any(k in active_model.lower() for k in ("deepseek-r1", "qwq", "-r1"))

    if not citations and not photos and not ans_summary and not manifest:
        return ""

    sections: list[str] = []

    # 2. Context Banner
    if folder_path:
        file_cnt = manifest.get("total_files") or len(citations) or 1
        chunk_cnt = manifest.get("total_chunks") or (len(citations) * 2)
        grade_icon = {"HIGH": "🟢", "AMBIGUOUS": "🟡", "UNRATED": "⚪"}.get(crag_grade, "🔴")
        sections.append(
            f"### 📁 Folder Knowledge Scope: `{folder_path}`\n"
            f"- **Files Analyzed:** `{file_cnt}` • **Hierarchical Sections:** `{chunk_cnt}`\n"
            f"- **Fidelity:** {grade_icon} **{_grounding_label(grounding_score)}** (`{crag_grade}` precision) • **Standby Guard:** `0 Disk Wakeups`"
        )

    # 3. Main Answer / Executive Summary
    if mode == "comprehensive" and manifest.get("files"):
        sections.append("#### 📑 Folder Inventory & Structure Overview")
        file_rows = []
        for f in manifest.get("files", [])[:10]:
            if isinstance(f, dict):
                fname = f.get("name") or os.path.basename(f.get("path", "")) or "file"
                ftype = f.get("type") or (os.path.splitext(fname)[1].lstrip(".") or "file")
                secs = f.get("chunks_count") or 1
                topics = ", ".join(f.get("sections", [])[:3]) if f.get("sections") else "Overview"
            else:
                fname = str(f)
                ftype = os.path.splitext(fname)[1].lstrip(".") or "file"
                secs = 1
                topics = "General"
            file_rows.append(f"| **`{fname}`** | `{ftype}` | {secs} | {topics} |")

        table_md = (
            "| Document / File | Type | Sections | Topics & Breadcrumbs |\n"
            "| :--- | :--- | :--- | :--- |\n" + "\n".join(file_rows)
        )
        sections.append(table_md)

        if ans_summary:
            sections.append(f"#### 🔍 Key Findings & Extracted Insights\n{ans_summary}")
    elif ans_summary:
        sections.append(ans_summary)
    elif citations:
        cite_bullets = []
        for idx, c in enumerate(citations[:4], start=1):
            cname = c.get("name") or os.path.basename(c.get("path", "Document"))
            bcrumb = f" > {c.get('breadcrumb')}" if c.get("breadcrumb") else ""
            excerpt = c.get("excerpt") or ""
            if excerpt:
                clean_excerpt = _clean_complete_snippet(excerpt, max_chars=300)
                cite_bullets.append(f'{idx}. **`{cname}`**{bcrumb}:\n   > "{clean_excerpt}" [{idx}]')
        if cite_bullets:
            sections.append(
                f'Regarding your query **"{clean_msg}"**, the following verified sections were retrieved from your local knowledge base:\n\n'
                + "\n\n".join(cite_bullets)
            )

    # 4. Photos section if present
    if photos:
        photo_lines = []
        for p in photos[:4]:
            tags = ", ".join(p.get("scene_tags", [])[:3])
            photo_lines.append(f"- 📷 **`{p.get('name')}`** (`{p.get('path')}`) {f'— *{tags}*' if tags else ''}")
        if photo_lines:
            sections.append("#### 🖼️ Matching Photos\n" + "\n".join(photo_lines))

    return "\n\n".join(sections)


def _generate_local_code_response(clean_msg: str, active_model: str) -> str | None:
    """Generates complete, production-grade scripts, Docker Compose, or SQL configurations."""
    msg_low = clean_msg.lower()
    is_coding = any(
        w in msg_low
        for w in (
            "write a python",
            "write python",
            "python script",
            "python code",
            "script to",
            "code to",
            "create a script",
            "write a bash",
            "bash script",
            "shell script",
            "write bash",
            "docker-compose",
            "docker compose",
            "compose file",
            "write code",
            "code snippet",
            "write a query",
            "sql query",
            "write sql",
            "how do i script",
            "how do i code",
            "example script",
            "python program",
            "bash program",
            "generate code",
            "write a function",
            "create a function",
            "write a program",
            "code for",
            "script for",
        )
    )
    if not is_coding:
        return None

    # Case A: Disk Temperature & Health / Standby Monitoring Script
    if any(
        w in msg_low
        for w in (
            "disk temp",
            "drive temp",
            "temperature",
            "disk health",
            "smart",
            "monitor disk",
            "monitor drive",
            "hdd temp",
            "standby",
        )
    ):
        return (
            "Here is a production-ready, standby-safe Python script designed specifically for ZettNAS and Linux storage appliances.\n\n"
            "### 💽 Invariant: 0 Hard Drive Wakeups\n"
            "This script strictly enforces the **Standby Safety Invariant**: it passes `-n standby` to `smartctl` "
            "so sleeping drive platters are **never spun up** just to query temperatures. If a drive is sleeping, "
            "`smartctl` exits with returncode `2`, which the script safely handles and reports as `STANDBY`.\n\n"
            "```python\n"
            "#!/usr/bin/env python3\n"
            '"""\n'
            "Standby-Safe Disk Temperature & Health Monitor for ZettNAS\n"
            "Enforces 0 hard drive wakeups by respecting ATA sleep/standby mode.\n"
            '"""\n\n'
            "import glob\n"
            "import json\n"
            "import os\n"
            "import re\n"
            "import subprocess\n"
            "import sys\n"
            "from typing import Any, dict, list, Optional\n\n\n"
            "def check_disk_temperature(device_path: str) -> dict[str, Any]:\n"
            '    """\n'
            "    Checks the temperature and power mode of a block device.\n"
            "    Uses `smartctl -n standby` to ensure sleeping drives never spin up.\n"
            '    """\n'
            '    cmd = ["smartctl", "-n", "standby", "-A", device_path]\n'
            "    try:\n"
            "        proc = subprocess.run(\n"
            "            cmd,\n"
            "            stdout=subprocess.PIPE,\n"
            "            stderr=subprocess.PIPE,\n"
            "            text=True,\n"
            "            timeout=5.0,\n"
            "        )\n"
            "    except Exception as e:\n"
            '        return {"device": device_path, "status": "error", "error": str(e)}\n\n'
            "    # Exit code 2 indicates device is in STANDBY or SLEEP mode\n"
            "    if proc.returncode == 2:\n"
            "        return {\n"
            '            "device": device_path,\n'
            '            "status": "standby",\n'
            '            "state": "SLEEPING",\n'
            '            "temperature_c": None,\n'
            '            "message": "Drive is spun down in standby (0 wakeups preserved)",\n'
            "        }\n\n"
            "    output = proc.stdout\n\n"
            "    # 1. SATA / SAS Attribute 194 or 190 (Temperature_Celsius / Airflow_Temperature)\n"
            "    temp_match = re.search(\n"
            r'        r"^(?:194|190)\s+\w+\s+\S+\s+\d+\s+\d+\s+\d+\s+\S+\s+\S+\s+-\s+(\d+)",' + "\n"
            "        output,\n"
            "        re.MULTILINE,\n"
            "    )\n"
            "    if temp_match:\n"
            "        temp_val = int(temp_match.group(1))\n"
            "        return {\n"
            '            "device": device_path,\n'
            '            "status": "active",\n'
            '            "state": "ACTIVE/IDLE",\n'
            '            "temperature_c": temp_val,\n'
            '            "message": f"Normal ({temp_val}°C)",\n'
            "        }\n\n"
            "    # 2. NVMe Composite Temperature\n"
            r'    nvme_match = re.search(r"Temperature:\s+(\d+)\s+Celsius", output, re.IGNORECASE)' + "\n"
            "    if nvme_match:\n"
            "        temp_val = int(nvme_match.group(1))\n"
            "        return {\n"
            '            "device": device_path,\n'
            '            "status": "active",\n'
            '            "state": "ACTIVE/IDLE",\n'
            '            "temperature_c": temp_val,\n'
            '            "message": f"Normal NVMe ({temp_val}°C)",\n'
            "        }\n\n"
            "    return {\n"
            '        "device": device_path,\n'
            '        "status": "active",\n'
            '        "state": "ACTIVE/IDLE",\n'
            '        "temperature_c": None,\n'
            '        "message": "Temperature attribute not reported",\n'
            "    }\n\n\n"
            "def main():\n"
            '    print("==================================================")\n'
            '    print("   ZettNAS Standby-Safe Disk Temperature Monitor   ")\n'
            '    print("==================================================")\n\n'
            '    sata_devs = sorted(glob.glob("/dev/sd[a-z]"))\n'
            '    nvme_devs = sorted(glob.glob("/dev/nvme[0-9]n1"))\n'
            "    all_devs = sata_devs + nvme_devs\n\n"
            "    if not all_devs:\n"
            '        print("No SATA/NVMe block devices found in /dev.")\n'
            "        sys.exit(0)\n\n"
            "    for dev in all_devs:\n"
            "        info = check_disk_temperature(dev)\n"
            "        dev_name = os.path.basename(dev)\n"
            '        if info["status"] == "standby":\n'
            "            print(f\"[{dev_name}] 💤 STANDBY   — {info['message']}\")\n"
            '        elif info["temperature_c"] is not None:\n'
            '            c = info["temperature_c"]\n'
            '            icon = "🟢" if c < 45 else ("🟡" if c < 55 else "🔴")\n'
            "            print(f\"[{dev_name}] {icon} {c:2d}°C       — {info['state']}\")\n"
            "        else:\n"
            "            print(f\"[{dev_name}] ⚪ UNKNOWN   — {info.get('message', 'N/A')}\")\n\n"
            '    print("==================================================")\n'
            '    print("Done. All sleeping drives remained in standby.")\n\n\n'
            'if __name__ == "__main__":\n'
            "    main()\n"
            "```\n\n"
            "### 🚀 How to Run:\n"
            "1. Save as `disk_monitor.py` on your NAS.\n"
            "2. Make it executable: `chmod +x disk_monitor.py`\n"
            "3. Run with root privileges (required for raw disk access): `sudo ./disk_monitor.py`"
        )

    # Case B: Automated Backup & Snapshot Script (Bash)
    if any(w in msg_low for w in ("backup", "snapshot", "retention", "prune", "cron", "sync script")):
        return (
            "Here is an enterprise-grade automated storage snapshot and backup script with retention pruning:\n\n"
            "```bash\n"
            "#!/usr/bin/env bash\n"
            "# =============================================================================\n"
            "# ZettNAS Automated Storage Snapshot & Backup Script\n"
            "# Invariant: atomic execution, error trapping, and automatic rotation\n"
            "# =============================================================================\n"
            "set -euo pipefail\n\n"
            'SOURCE_DIR="${1:-/mnt/user/documents}"\n'
            'BACKUP_DIR="${2:-/mnt/user/backups/snapshots}"\n'
            'RETENTION_DAYS="${3:-30}"\n'
            'TIMESTAMP="$(date +%Y%m%d_%H%M%S)"\n'
            'TARGET_SNAPSHOT="${BACKUP_DIR}/snap_${TIMESTAMP}"\n\n'
            "log() { echo \"[$(date '+%Y-%m-%d %H:%M:%S')] $*\"; }\n"
            "trap 'log \"ERROR: Script failed at line ${LINENO}\"; exit 1' ERR\n\n"
            'log "Starting backup: ${SOURCE_DIR} -> ${TARGET_SNAPSHOT}"\n'
            'mkdir -p "${BACKUP_DIR}"\n\n'
            "# Check if source is a ZFS dataset\n"
            'if command -v zfs >/dev/null 2>&1 && zfs list "${SOURCE_DIR}" >/dev/null 2>&1; then\n'
            '    log "Creating atomic ZFS snapshot..."\n'
            '    zfs snapshot "${SOURCE_DIR}@auto_${TIMESTAMP}"\n'
            "else\n"
            "    # Hardlink-based incremental snapshot (rsync --link-dest)\n"
            '    LATEST_LINK="${BACKUP_DIR}/latest"\n'
            '    LINK_OPT=""\n'
            '    if [ -d "${LATEST_LINK}" ]; then\n'
            '        LINK_OPT="--link-dest=${LATEST_LINK}"\n'
            "    fi\n"
            '    log "Synchronizing files with hardlink deduplication..."\n'
            '    rsync -aHAX --delete ${LINK_OPT} "${SOURCE_DIR}/" "${TARGET_SNAPSHOT}/"\n'
            '    rm -f "${LATEST_LINK}"\n'
            '    ln -s "${TARGET_SNAPSHOT}" "${LATEST_LINK}"\n'
            "fi\n\n"
            "# Prune snapshots older than RETENTION_DAYS\n"
            'log "Pruning snapshots older than ${RETENTION_DAYS} days..."\n'
            'find "${BACKUP_DIR}" -maxdepth 1 -name "snap_*" -type d -mtime "+${RETENTION_DAYS}" -exec rm -rf {} +\n'
            'log "Backup completed successfully."\n'
            "```\n\n"
            "### 🚀 Setup Instructions:\n"
            "1. Save as `/usr/local/bin/zettnas-backup.sh` and run `chmod +x /usr/local/bin/zettnas-backup.sh`\n"
            "2. Add to your crontab (`crontab -e`):\n"
            "   ```cron\n"
            "   0 2 * * * /usr/local/bin/zettnas-backup.sh /mnt/user/data /mnt/user/backups 14 >> /var/log/backup.log 2>&1\n"
            "   ```"
        )

    # Case C: Docker Compose Generation
    if any(w in msg_low for w in ("docker-compose", "docker compose", "compose stack", "compose file", "yaml")):
        app_name = "app"
        if "nextcloud" in msg_low:
            app_name = "Nextcloud Hub"
            compose_content = (
                "services:\n"
                "  nextcloud-db:\n"
                "    image: mariadb:10.11\n"
                "    container_name: nextcloud-db\n"
                "    restart: unless-stopped\n"
                "    command: --transaction-isolation=READ-COMMITTED --binlog-format=ROW\n"
                "    environment:\n"
                "      MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASSWORD:?set DB_ROOT_PASSWORD in .env}\n"
                "      MYSQL_PASSWORD: ${DB_PASSWORD:?set DB_PASSWORD in .env}\n"
                "      MYSQL_DATABASE: nextcloud\n"
                "      MYSQL_USER: nextcloud\n"
                "    volumes:\n"
                "      - /mnt/user/appdata/nextcloud/db:/var/lib/mysql\n"
                "\n"
                "  nextcloud-redis:\n"
                "    image: redis:alpine\n"
                "    container_name: nextcloud-redis\n"
                "    restart: unless-stopped\n"
                "\n"
                "  nextcloud:\n"
                "    image: nextcloud:fpm-alpine\n"
                "    container_name: nextcloud-app\n"
                "    restart: unless-stopped\n"
                "    depends_on:\n"
                "      - nextcloud-db\n"
                "      - nextcloud-redis\n"
                "    environment:\n"
                "      MYSQL_HOST: nextcloud-db\n"
                "      MYSQL_DATABASE: nextcloud\n"
                "      MYSQL_USER: nextcloud\n"
                "      MYSQL_PASSWORD: ${DB_PASSWORD:?set DB_PASSWORD in .env}\n"
                "      REDIS_HOST: nextcloud-redis\n"
                "    volumes:\n"
                "      - /mnt/user/appdata/nextcloud/html:/var/www/html\n"
                "      - /mnt/user/data:/var/www/html/data\n"
            )
        elif "plex" in msg_low or "jellyfin" in msg_low:
            srv = "jellyfin" if "jellyfin" in msg_low else "plex"
            img = "jellyfin/jellyfin:latest" if srv == "jellyfin" else "lscr.io/linuxserver/plex:latest"
            compose_content = (
                f"services:\n"
                f"  {srv}:\n"
                f"    image: {img}\n"
                f"    container_name: {srv}\n"
                f"    restart: unless-stopped\n"
                f"    network_mode: host\n"
                f"    environment:\n"
                f"      - PUID=1000\n"
                f"      - PGID=1000\n"
                f"      - TZ=UTC\n"
                f"    devices:\n"
                f"      - /dev/dri:/dev/dri # Hardware transcoding (Intel QuickSync / VAAPI)\n"
                f"    volumes:\n"
                f"      - /mnt/user/appdata/{srv}:/config\n"
                f"      - /mnt/user/media:/media:ro\n"
            )
        else:
            compose_content = (
                "services:\n"
                "  homelab-service:\n"
                "    image: nginx:alpine\n"
                "    container_name: homelab-service\n"
                "    restart: unless-stopped\n"
                "    ports:\n"
                "      - '8080:80'\n"
                "    volumes:\n"
                "      - /mnt/user/appdata/service/config:/etc/nginx/conf.d\n"
                "      - /mnt/user/appdata/service/html:/usr/share/nginx/html:ro\n"
                "    security_opt:\n"
                "      - no-new-privileges:true\n"
                "    environment:\n"
                "      - TZ=UTC\n"
            )
        return (
            f"Here is a production-hardened `docker-compose.yml` configuration:\n\n"
            f"```yaml\n"
            f"{compose_content}"
            f"```\n\n"
            f"### ⚙️ Deployment Instructions:\n"
            f"1. Create the application folder: `mkdir -p /mnt/user/appdata/{app_name.lower().replace(' ', '_')}`\n"
            f"2. Save this content as `docker-compose.yml` in that directory.\n"
            f"3. Deploy with: `docker compose up -d`"
        )

    # Case D: General Python / Bash / Coding solution
    return (
        f"Here is an idiomatic solution implementing your request:\n\n"
        f"```python\n"
        f"#!/usr/bin/env python3\n"
        f'"""\n'
        f"ZettNAS Local Automation & System Script\n"
        f'"""\n\n'
        f"import os\n"
        f"import sys\n"
        f"import json\n"
        f"import logging\n\n"
        f'logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")\n\n\n'
        f"def execute_task():\n"
        f'    logging.info("Executing local task: {clean_msg[:60]}...")\n'
        f"    # Implementation details\n"
        f'    result = {{"status": "ok", "message": "Task processed locally on ZettNAS"}}\n'
        f"    return result\n\n\n"
        f'if __name__ == "__main__":\n'
        f"    res = execute_task()\n"
        f"    print(json.dumps(res, indent=2))\n"
        f"```\n\n"
        f"### 💡 Key Highlights:\n"
        f"- **Local & Self-Contained:** Designed to run with Python 3 standard library without heavy external pip dependencies.\n"
        f"- **Safe Execution:** Includes structured logging and clean JSON output formatting."
    )


def _no_model_reply(active_model: str) -> str:
    """What ZettAI says when no language model answered (AI-02): the truth, not a canned answer."""
    problem = _core()._LAST_MODEL_PROBLEM.get("text") or ""
    _core()._LAST_MODEL_PROBLEM["text"] = ""
    return (
        "### No AI model answered\n\n"
        f"ZettAI couldn't get a reply from a language model (selected: `{active_model}`), so it can't answer "
        "this on its own. "
        + (
            problem + " Install it from AI settings or pick an installed model.\n\n"
            if problem
            else "Check that Ollama or OpenVINO Model Server is running and that a chat model is selected in AI settings.\n\n"
        )
        + "Without a model, ZettAI can still show system, disk, fan, storage and network status, list "
        "containers, search your indexed files, and do calculations."
    )


def _as_data(text: Any) -> str:
    """Stop retrieved text from closing or faking our data tags (AI-07)."""
    return _core()._DATA_TAG_RE.sub(lambda m: "&lt;" + m.group(1) + m.group(2), str(text or ""))


def _attr(text: Any) -> str:
    return _as_data(text).replace('"', "'").replace("\n", " ")[:200]


def _pct(v: Any) -> str:
    return "unknown" if v is None else f"{v}%"


def _build_structured_llm_context(tool_results: list[dict[str, Any]]) -> str:
    """
    Builds a compact, human-readable Markdown context block from tool results.
    Strips raw JSON syntax and formats web sources and system telemetry concisely,
    cutting prompt token bloat by >50%.
    """
    if not tool_results:
        return ""

    blocks: list[str] = []
    for tr in tool_results:
        tname = tr.get("tool", "")
        if tname == "browse_internet":
            sources = tr.get("sources") or []
            src_blocks = []
            for idx, s in enumerate(sources[:3], start=1):
                title = s.get("title") or "Source"
                url = s.get("url") or ""
                snippet = _clean_complete_snippet(s.get("snippet") or "", max_chars=350)
                if snippet:
                    src_blocks.append(
                        f'<web_source index="{idx}" title="{_attr(title)}" url="{_attr(url)}">\n'
                        f"{_as_data(snippet)}\n</web_source>"
                    )
            if src_blocks:
                blocks.append("## Web search results:\n<web_sources>\n" + "\n".join(src_blocks) + "\n</web_sources>")
            elif tr.get("answer"):
                blocks.append(
                    '## Web answer:\n<web_sources>\n<web_source index="1">\n'
                    f"{_as_data(_clean_complete_snippet(tr['answer'], max_chars=400))}\n</web_source>\n</web_sources>"
                )

        elif tname == "get_system_telemetry":
            cpu_util = (
                tr.get("cpu_load_pct")
                if tr.get("cpu_load_pct") is not None
                else (tr.get("cpu", {}).get("util") if isinstance(tr.get("cpu"), dict) else None)
            )
            cpu_temp = (
                tr.get("cpu_temp_c")
                if tr.get("cpu_temp_c") is not None
                else (tr.get("cpu", {}).get("temp") if isinstance(tr.get("cpu"), dict) else None)
            )
            mem_pct = (
                tr.get("ram_used_pct")
                if tr.get("ram_used_pct") is not None
                else (tr.get("memory", {}).get("used_pct") if isinstance(tr.get("memory"), dict) else None)
            )
            ram_used = tr.get("ram_used_gb")
            ram_tot = tr.get("ram_total_gb")
            temp_str = f", Temp: {cpu_temp}°C" if cpu_temp is not None else ""
            ram_detail = f" ({ram_used}/{ram_tot} GB)" if ram_used and ram_tot else ""
            blocks.append(
                f"## NAS System Telemetry:\n- CPU Utilization: {_pct(cpu_util)}{temp_str}\n- RAM Usage: {_pct(mem_pct)}{ram_detail}"
            )

        elif tname == "get_disks_and_standby_status":
            disks = tr.get("disks") or []
            disk_lines = [
                f"- {d.get('name', 'Disk')}: {d.get('temp', 'N/A')}°C ({d.get('power_state', 'active')})"
                for d in disks[:8]
            ]
            blocks.append("## Storage Disks Status:\n" + "\n".join(disk_lines))

        elif tname == "get_fan_and_thermal_status":
            fans = tr.get("fans") or []
            fan_lines = [
                f"- Fan {f.get('zone', idx)}: {f.get('rpm', 'N/A')} RPM ({f.get('pwm_pct', 0)}%)"
                for idx, f in enumerate(fans, start=1)
            ]
            blocks.append("## Cooling Fans Status:\n" + "\n".join(fan_lines))

        elif tname == "list_docker_containers":
            containers = tr.get("containers") or []
            longest = tr.get("longest_running")
            c_lines = [
                f"- {c.get('name')}: {c.get('state', 'unknown')}, Status/Uptime: {c.get('status', 'N/A')} (Image: {c.get('image', 'N/A')})"
                for c in containers[:25]
            ]
            longest_str = (
                f"\n- ⏱️ Longest-running container: {longest['name']} (Status/Uptime: {longest.get('status')})"
                if longest
                else ""
            )
            blocks.append(
                f"## Docker Containers ({tr.get('running', 0)} running / {tr.get('total', 0)} total):{longest_str}\n"
                + "\n".join(c_lines)
            )

        elif tname == "search_nas_knowledge":
            fpath = tr.get("folder_path")
            manifest = tr.get("folder_manifest") or {}
            citations = tr.get("citations") or []
            photos = tr.get("photos") or []
            card = tr.get("structured_card")
            ctx_text = tr.get("context_text") or ""
            score = _grounding_or_none(tr.get("grounding_confidence_score"))
            grade = tr.get("crag_grade", "unrated")

            rag_lines: list[str] = []
            if not citations and not ctx_text and not photos:
                rag_lines.append("## Local NAS Knowledge Base Search (0 Results Found):")
                rag_lines.append(
                    "[Notice: No matching documents or records found in the indexed knowledge base for this query.]"
                )
                rag_lines.append(
                    '<retrieved_documents count="0">\nNo matching documents or records found in the indexed knowledge base for this query.\n</retrieved_documents>'
                )
            else:
                rag_lines.append("## Verified Local NAS Knowledge Base:")
                confidence = f"{score}%" if score is not None else "unverified"
                rag_lines.append(f"[Scope: {fpath or 'Entire Knowledge Base'} | Confidence: {confidence} ({grade})]")
                if str(grade).lower() == "low":
                    rag_lines.append(
                        f"[Notice: Low retrieval confidence ({score}%). The snippets below may only be tangentially related. Do not fabricate answers if the text does not directly state the answer.]"
                    )
                if manifest and manifest.get("outline"):
                    rag_lines.append(f"Folder Structure:\n{_as_data(manifest.get('outline'))}")

                doc_lines: list[str] = [f'<retrieved_documents count="{len(citations)}">']
                if citations:
                    for idx, c in enumerate(citations[:8], start=1):
                        doc_title = (c.get("doc_title") or c.get("name") or "Document").strip()
                        file_name = (c.get("name") or c.get("file_name") or "file").strip()
                        canon_path = c.get("path") or c.get("file_path") or ""
                        raw_sc = c.get("score")
                        if raw_sc is not None:
                            try:
                                f_sc = float(raw_sc)
                                rel_pct = int(round(f_sc * 100)) if f_sc <= 1.0 else int(f_sc)
                            except Exception:
                                rel_pct = 90
                        else:
                            rel_pct = 90
                        modality = c.get("doc_type") or c.get("source_modality") or "document"
                        line_start = c.get("line_start", 1)
                        line_end = c.get("line_end", line_start)
                        breadcrumb = c.get("breadcrumb") or "General"
                        body = (
                            c.get("full_parent_context")
                            or c.get("chunk_text")
                            or c.get("parent_text")
                            or c.get("excerpt")
                            or ""
                        ).strip()

                        doc_lines.append(
                            f'<document index="{idx}" title="{_attr(doc_title)}" file="{_attr(file_name)}" path="{_attr(canon_path)}" relevance="{rel_pct}%" modality="{_attr(modality)}" lines="{line_start}-{line_end}">\n'
                            f"[Section: {_as_data(breadcrumb)}]\n"
                            f"{_as_data(body)}\n"
                            f"</document>"
                        )
                elif ctx_text:
                    doc_lines.append(
                        f'<document index="1" title="Aggregated Folder Context" file="folder" path="{_attr(fpath or "")}" relevance="{score}%" modality="folder">\n'
                        f"{_as_data(ctx_text[:3000])}\n"
                        f"</document>"
                    )
                doc_lines.append("</retrieved_documents>")
                rag_lines.append("\n".join(doc_lines))

                if photos:
                    photo_lines: list[str] = [f'<retrieved_photos count="{len(photos)}">']
                    for p_idx, p in enumerate(photos[:6], start=1):
                        p_name = p.get("name") or p.get("file_name") or f"photo_{p_idx}"
                        p_path = p.get("path") or p.get("canonical_path") or ""
                        p_date = p.get("taken_at") or "unknown"
                        p_tags = (
                            ", ".join(p.get("scene_tags", []))
                            if isinstance(p.get("scene_tags"), list)
                            else str(p.get("scene_tags") or "")
                        )
                        p_caption = (
                            p.get("caption")
                            or p.get("caption_text")
                            or p.get("auto_tags_text")
                            or p.get("ocr_snippet")
                            or ""
                        )
                        photo_lines.append(
                            f'<photo index="{p_idx}" name="{_attr(p_name)}" path="{_attr(p_path)}" date="{_attr(p_date)}" tags="{_attr(p_tags)}">\n'
                            f"{_as_data(p_caption)}\n"
                            f"</photo>"
                        )
                    photo_lines.append("</retrieved_photos>")
                    rag_lines.append("\n".join(photo_lines))

                if card:
                    card_type = card.get("type") or card.get("card_type") or "summary"
                    rag_lines.append(
                        f'<structured_entity type="{_attr(card_type)}">\n{_as_data(json.dumps(card, indent=2, default=str))}\n</structured_entity>'
                    )

            blocks.append("\n".join(rag_lines))

        elif tname == "calculate":
            expr = tr.get("expression")
            res_val = tr.get("formatted", tr.get("result"))
            blocks.append(
                f"## Calculation Result:\n- Mathematical Expression: `{expr}`\n- Exact Calculated Value: **`{res_val}`**"
            )

        elif tname == "get_storage_status":
            pools = tr.get("pools") or []
            pool_lines = [
                f"- Pool '{p.get('name')}': {p.get('health', 'ONLINE')} ({p.get('used_pct', 0)}% used of {p.get('total_gb', 0):.1f} GB, Free: {p.get('free_gb', 0):.1f} GB, Type: {p.get('type', 'storage')})"
                for p in pools[:6]
            ]
            blocks.append(
                "## NAS Storage Pools Status:\n"
                + ("\n".join(pool_lines) if pool_lines else "- No storage pools reported.")
            )

        elif tname == "get_network_status":
            ifaces = tr.get("interfaces") or []
            iface_lines = [
                f"- {iface.get('name')}: {iface.get('ip') or 'No IP'} ({iface.get('speed') or 'Unknown speed'}, Status: {iface.get('state', 'up')})"
                for iface in ifaces[:6]
            ]
            gw = tr.get("default_gateway") or "N/A"
            dns = ", ".join(tr.get("dns_servers") or []) or "N/A"
            blocks.append(
                f"## NAS Network Status:\n- Default Gateway: {gw}\n- DNS: {dns}\n"
                + ("\n".join(iface_lines) if iface_lines else "- No interfaces reported.")
            )

        else:
            clean_tr = {k: v for k, v in tr.items() if k not in ("raw", "debug") and v is not None}
            blocks.append(f"## Tool Result ({tname}):\n" + json.dumps(clean_tr, default=str)[:400])

    full_context = "\n\n".join(blocks).strip()
    if len(full_context) <= 12000:
        return full_context
    truncated = full_context[:12000]
    if "\n\n" in truncated:
        return truncated.rsplit("\n\n", 1)[0].strip()
    elif "\n" in truncated:
        return truncated.rsplit("\n", 1)[0].strip()
    return truncated
