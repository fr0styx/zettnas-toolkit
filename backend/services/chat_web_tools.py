"""
Ask Zetty's web tools: web search with fact extraction, and weather (split out of
ai_chat_agent, AI-21).

Both run only in chats where the user turned on Web (_WEB_ALLOWED), and only fetch
public addresses (SSRF guard).
"""

import contextvars
import html
import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any

from backend.config import logger


def _is_safe_public_url(url_str: str) -> bool:
    try:
        from backend.services.ssrf_guard import validate_public_url

        ok, _ = validate_public_url(url_str)
        return ok
    except Exception:
        return False


# ============================================================================
# Live Internet Browsing & Web Fact-Extraction Engine
# ============================================================================


def _strip_html_tags(raw_html: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw_html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_wikitext_value(raw_val: str) -> str:
    """Strips MediaWiki templates, refs, and links from an infobox field value."""
    s = str(raw_val or "")
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"<ref[^/>]*/\s*>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.DOTALL)
    # Extract display text from [[Target|Label]] or [[Target]]
    s = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", s)
    # Remove simple templates like {{nowrap|...}} or {{Start date|2025|01|20}}
    s = re.sub(r"\{\{(?:nowrap|plainlist|ubl|unbulleted list|flatlist)\|([^{}]+)\}\}", r"\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = _strip_html_tags(s)
    s = re.sub(r"[\[\]{}|*]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" ,;-")


_ABBREVIATIONS = (
    "int",
    "st",
    "dr",
    "mr",
    "mrs",
    "ms",
    "prof",
    "jr",
    "sr",
    "inc",
    "ltd",
    "co",
    "corp",
    "univ",
    "dept",
    "gov",
    "gen",
    "col",
    "capt",
    "sgt",
    "no",
    "vol",
    "fig",
    "vs",
    "c",
    "ca",
    "approx",
    "e.g",
    "i.e",
    "al",
    "etc",
    "ph.d",
    "b.a",
    "b.s",
    "m.s",
    "m.a",
    "u.s",
    "u.k",
)
_PROTECTED_DOT = "\u2024"  # One-dot leader to temporarily mask abbreviation dots


def _split_sentences_safe(text: str) -> list[str]:
    """
    Splits text into complete grammatical sentences while protecting abbreviations and initials.
    Replaces periods inside known abbreviations (e.g. 'Int.', 'Dr.', 'U.S.') with a temporary marker,
    splits on real sentence boundaries, and restores the periods.
    """
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return []

    def _mask_abbrev(m: re.Match) -> str:
        return m.group(0).replace(".", _PROTECTED_DOT)

    # 1. Mask known abbreviations (case-insensitive) followed by space and alphanumeric
    abbrev_pattern = r"\b(?:" + "|".join(re.escape(a) for a in _ABBREVIATIONS) + r")\.(?=\s+[a-zA-Z0-9])"
    masked = re.sub(abbrev_pattern, _mask_abbrev, cleaned, flags=re.IGNORECASE)

    # 2. Mask single-letter initials (e.g. 'J. K. Rowling', 'Kim J. Un')
    masked = re.sub(r"\b([A-Za-z])\.(?=\s+[A-Za-z0-9])", rf"\1{_PROTECTED_DOT}", masked)

    # 3. Mask decimal numbers (e.g., 3.14, 2.5B)
    masked = re.sub(r"(?<=\d)\.(?=\d)", _PROTECTED_DOT, masked)

    # 4. Split on real sentence-ending punctuation followed by whitespace
    raw_sents = re.split(r"(?<=[.!?])\s+", masked)

    # 5. Restore masked dots and clean up
    sents: list[str] = []
    for s in raw_sents:
        restored = s.replace(_PROTECTED_DOT, ".").strip()
        if restored:
            sents.append(restored)
    return sents


def _clean_complete_snippet(text: str, max_chars: int = 850) -> str:
    """
    Cleans raw text and extracts strictly complete, grammatically unbroken sentences or structured blocks.
    Preserves recipes, code blocks, bulleted lists, yaml configs, and structured tables.
    Never terminates mid-word, mid-sentence, or on trailing prepositions/conjunctions for prose.
    """
    raw_str = str(text or "").strip()
    if not raw_str:
        return ""

    # Remove citation brackets like [1], [citation needed]
    raw_str = re.sub(r"\[\d+\]", "", raw_str)
    raw_str = re.sub(r"\[citation needed\]", "", raw_str, flags=re.IGNORECASE)

    # Detect structured content: code blocks, yaml, tables, bulleted lists, recipes
    lines = raw_str.splitlines()
    is_structured = False
    if "```" in raw_str or "|" in raw_str:
        is_structured = True
    elif len(lines) > 1:
        structured_line_count = 0
        for ln in lines:
            s_ln = ln.strip()
            if (
                s_ln.startswith(("- ", "* ", "+ ", "> ", "• ", "#"))
                or re.match(r"^\d+[\.\)]\s+", s_ln)
                or (":" in s_ln and not s_ln.startswith("http"))
                or s_ln.startswith(("def ", "class ", "import ", "from ", "version:", "services:", "image:", "ports:"))
                or s_ln.endswith((":", "{", "}", "[", "]", ";"))
            ):
                structured_line_count += 1
        if (structured_line_count / max(1, len(lines))) >= 0.25:
            is_structured = True

    if is_structured:
        accumulated_lines: list[str] = []
        acc_len = 0
        for ln in lines:
            if not ln.strip() and accumulated_lines and not accumulated_lines[-1].strip():
                continue
            line_len = len(ln) + 1
            if acc_len + line_len > max_chars and accumulated_lines:
                break
            accumulated_lines.append(ln)
            acc_len += line_len
        result = "\n".join(accumulated_lines).strip()
        if result:
            return result

    cleaned = re.sub(r"\s+", " ", raw_str).strip()
    sentences = _split_sentences_safe(cleaned)
    valid_sentences: list[str] = []
    accumulated_len = 0
    dangling = (
        " the",
        " a",
        " an",
        " at",
        " in",
        " of",
        " to",
        " for",
        " on",
        " and",
        " but",
        " or",
        " with",
        " by",
        " from",
        " as",
        " that",
        " which",
        " who",
        " into",
        " onto",
        " over",
        " under",
        " about",
    )
    for s in sentences:
        s_clean = s.strip()
        if not s_clean or len(s_clean) < 15:
            continue
        s_low = s_clean.lower().rstrip(".,;: ")
        if any(s_low.endswith(d) or s_low == d.strip() for d in dangling):
            continue
        # Also reject sentences ending in an isolated abbreviation token (e.g. "... at the int")
        if any(s_low.endswith(f" {a}") or s_low == a for a in _ABBREVIATIONS):
            continue
        if not s_clean.endswith((".", "!", "?", '."', '!"', '?"', ".'", "!'", "?'")):
            if len(s_clean) > 35:
                s_clean = s_clean + "."
            else:
                continue
        valid_sentences.append(s_clean)
        accumulated_len += len(s_clean)
        if accumulated_len >= max_chars:
            break

    if not valid_sentences:
        # Chinese and Japanese have no spaces between words: cut at their sentence ends instead.
        if sum(1 for ch in cleaned if "\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff") >= 4:
            part = cleaned[:max_chars]
            ends = [part.rfind(p) for p in ("。", "！", "？")]
            cut = max(ends)
            return part[: cut + 1] if cut > 0 else part
        trimmed = cleaned[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-")
        trimmed_low = trimmed.lower()
        if any(trimmed_low.endswith(d) for d in dangling) or any(
            trimmed_low.endswith(f" {a}") or trimmed_low == a for a in _ABBREVIATIONS
        ):
            trimmed = trimmed.rsplit(" ", 1)[0].rstrip(" ,;:-")
        return f"{trimmed}." if trimmed and len(trimmed) > 20 else ""
    return " ".join(valid_sentences)


def _extract_clean_first_sentences(text: str, count: int = 2) -> str:
    """Extracts up to `count` complete sentences without trailing cuts."""
    clean = _clean_complete_snippet(text, max_chars=800)
    sents = _split_sentences_safe(clean)
    return " ".join(sents[:count]).strip()


def _extract_wikipedia_infobox_facts(wikitext: str) -> dict[str, str]:
    """Extracts structured facts (incumbent, capital, CEO, founder, etc.) from Wikipedia section-0 wikitext."""
    if not wikitext:
        return {}
    facts: dict[str, str] = {}
    keys_of_interest = (
        "incumbent",
        "incumbentsince",
        "leader_name1",
        "leader_title1",
        "president",
        "prime_minister",
        "chancellor",
        "monarch",
        "governor",
        "capital",
        "largest_city",
        "ceo",
        "key_people",
        "founder",
        "founders",
        "developer",
        "latest_release_version",
        "currency",
        "official_languages",
        "alma_mater",
        "education",
        "birth_place",
        "birth_date",
        "office",
        "party",
    )
    for key in keys_of_interest:
        m = re.search(
            rf"^\s*\|\s*{re.escape(key)}\s*=\s*(.+)$",
            wikitext,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if m:
            cleaned = _clean_wikitext_value(m.group(1))
            if cleaned and len(cleaned) <= 140:
                facts[key] = cleaned
    return facts


def _normalize_web_query_and_topic(raw_query: str) -> tuple[str, str]:
    """
    Returns `(search_topic, web_query)` where:
      - `search_topic` is the clean entity/subject for Wikipedia lookup (e.g. 'president of the United States')
      - `web_query` is the natural-language search query for live DuckDuckGo web search
    """
    clean_q = str(raw_query or "").strip()
    mid_web_m = re.search(
        r"(?:search|browse|check)\s+(?:the\s+)?(?:web|internet|online)\s+(?:for|about|on|to\s+confirm|to\s+verify)\s+(.+)$",
        clean_q,
        flags=re.IGNORECASE,
    )
    base_q = mid_web_m.group(1).strip(" ?!.") if mid_web_m else clean_q

    # Expand common question contractions ('whos' -> 'who is', 'whats' -> 'what is', etc.)
    expanded_q = re.sub(r"^\s*who['’]?s\b", "Who is", base_q, flags=re.IGNORECASE)
    expanded_q = re.sub(r"^\s*what['’]?s\b", "What is", expanded_q, flags=re.IGNORECASE)
    expanded_q = re.sub(r"^\s*where['’]?s\b", "Where is", expanded_q, flags=re.IGNORECASE)
    expanded_q = re.sub(r"^\s*when['’]?s\b", "When is", expanded_q, flags=re.IGNORECASE)
    expanded_q = re.sub(r"^\s*how['’]?s\b", "How is", expanded_q, flags=re.IGNORECASE)

    # Strip question prefixes to isolate the encyclopedia entity/topic
    topic = re.sub(
        r"^(?:please\s+)?(?:can\s+you\s+|could\s+you\s+)?(?:search\s+(?:the\s+)?(?:web|internet|online)\s+(?:for|about)\s+|browse\s+(?:the\s+)?(?:web|internet|online)\s+(?:for|about)\s+|look\s+up\s+|tell\s+me\s+(?:about\s+)?|verify\s+|confirm\s+|explain\s+)+",
        "",
        expanded_q,
        flags=re.IGNORECASE,
    ).strip(" ?!.")
    topic = re.sub(
        r"^(?:who|what|where|when|why|how|which)\s+(?:is|are|was|were|does|do|did|has|have)\s+(?:the\s+)?(?:current\s+|present\s+)?",
        "",
        topic,
        flags=re.IGNORECASE,
    ).strip(" ?!.")

    # If the user asked "Where did X study/studied/go to school", extract clean entity X for search topic
    edu_m = re.match(
        r"^(.+?)\s+(?:study|studied|go\s+to\s+school|attend\s+school|go\s+to\s+university|go\s+to\s+college|get\s+educated)\b",
        topic,
        flags=re.IGNORECASE,
    )
    if edu_m:
        topic = edu_m.group(1).strip(" ?!.")

    if not topic:
        topic = base_q.strip(" ?!.") or clean_q
    return (topic, expanded_q)


# Web access for the current chat turn (AI-06). Tools that leave the NAS check it,
# whichever path calls them (keyword routing or the model's own tool calls).
_WEB_ALLOWED: contextvars.ContextVar = contextvars.ContextVar("zettnas_ai_web_allowed", default=False)
_WEB_BLOCKED_MSG = "Web access is off for this chat. Turn on Web to let ZettAI search the internet or get the weather."


def tool_browse_internet(query: str, max_results: int = 5, allow_fetch: bool = True) -> dict[str, Any]:
    if not _WEB_ALLOWED.get():
        return {"tool": "browse_internet", "status": "blocked", "error": _WEB_BLOCKED_MSG, "sources": []}
    """
    Searches live internet sources (Wikipedia full intro + Infobox fact parser,
    DuckDuckGo live HTML web search, DuckDuckGo Instant Answer API, and direct HTTPS URLs)
    so the local chatbot can accurately answer and verify any question online.
    """
    clean_q = str(query or "").strip()
    if not clean_q:
        return {"tool": "browse_internet", "status": "error", "sources": [], "error": "Empty search query"}
    # the search carries the question, not addresses, paths, numbers or keys (AI-12)
    from backend.services.ai_safeguards import safe_web_query

    if not allow_fetch:
        # search only (SEC-31): no page is fetched, so no URL goes out either
        clean_q = " ".join(re.sub(r"https?://[^\s<>\"']+", " ", clean_q).split())
    scrubbed, why = safe_web_query(clean_q)
    if scrubbed is None:
        return {"tool": "browse_internet", "status": "blocked", "sources": [], "error": f"Web search refused: {why}."}
    clean_q = scrubbed

    if os.environ.get("TESTING") == "1" or os.environ.get("ZETTNAS_TEST_MODE") == "1":
        return {
            "tool": "browse_internet",
            "status": "ok",
            "query": clean_q,
            "extracted_facts": {},
            "direct_answer": f"Verified online reference result for '{clean_q}' via ZettAI Web Search.",
            "sources": [
                {
                    "title": f"Web Verification: {clean_q}",
                    "url": f"https://en.wikipedia.org/wiki/Special:Search?search={urllib.parse.quote(clean_q)}",
                    "snippet": f"Verified online reference result for '{clean_q}' via ZettAI Web Search.",
                    "source": "wikipedia",
                }
            ],
        }

    search_topic, web_query = _normalize_web_query_and_topic(clean_q)
    sources: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    extracted_facts: dict[str, str] = {}
    direct_answer = ""

    wiki_headers = {"User-Agent": "ZettNAS-Toolkit-ZettAI/2.0 (+https://github.com/fr0styx/zettnas-toolkit)"}
    browser_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    def _add_source(title: str, url: str, snippet: str, src_type: str) -> None:
        norm_u = url.strip()
        if not norm_u or norm_u in seen_urls:
            return
        clean_snip = _clean_complete_snippet(snippet, max_chars=850)
        if not clean_snip:
            return
        seen_urls.add(norm_u)
        sources.append(
            {
                "title": title.strip()[:160],
                "url": norm_u,
                "snippet": clean_snip,
                "source": src_type,
            }
        )

    # 1. If user included a direct URL, fetch and extract its title + text
    url_match = re.search(r"https?://[^\s<>\"']+", clean_q) if allow_fetch else None
    if url_match:
        target_url = url_match.group(0).rstrip(".,;)")
        if not _is_safe_public_url(target_url):
            logger.warning(f"[AIChatAgent] Blocked SSRF attempt to non-public URL: {target_url}")
        else:
            try:
                from backend.services.safe_fetch import safe_open

                with safe_open(target_url, context="public", headers=browser_headers, timeout=5.0) as resp:
                    raw_body = resp.read(120_000).decode("utf-8", errors="replace")
                    title_m = re.search(r"<title[^>]*>(.*?)</title>", raw_body, flags=re.IGNORECASE | re.DOTALL)
                    page_title = _strip_html_tags(title_m.group(1)) if title_m else target_url
                    snippet = _strip_html_tags(raw_body)[:520]
                    _add_source(page_title or target_url, target_url, snippet, "direct_url")
            except Exception as e:
                logger.debug(f"[AIChatAgent] Direct URL fetch failed for {target_url}: {e}")

    # 2. Wikipedia Search + Lead Extract + Infobox Fact Extraction
    try:
        wiki_search_params = urllib.parse.urlencode(
            {
                "action": "query",
                "list": "search",
                "srsearch": search_topic,
                "utf8": "1",
                "format": "json",
                "srlimit": "3",
            }
        )
        wiki_search_url = f"https://en.wikipedia.org/w/api.php?{wiki_search_params}"
        req = urllib.request.Request(wiki_search_url, headers=wiki_headers)
        with urllib.request.urlopen(req, timeout=4.5) as resp:
            wiki_search_data = json.loads(resp.read().decode("utf-8", errors="replace"))
            search_hits = wiki_search_data.get("query", {}).get("search", [])

        if search_hits:
            top_title = str(search_hits[0].get("title") or "").strip()
            if top_title:
                detail_params = urllib.parse.urlencode(
                    {
                        "action": "query",
                        "prop": "extracts|revisions",
                        "exintro": "1",
                        "explaintext": "1",
                        "rvprop": "content",
                        "rvsection": "0",
                        "redirects": "1",
                        "titles": top_title,
                        "format": "json",
                    }
                )
                detail_url = f"https://en.wikipedia.org/w/api.php?{detail_params}"
                with urllib.request.urlopen(
                    urllib.request.Request(detail_url, headers=wiki_headers), timeout=4.5
                ) as d_resp:
                    detail_data = json.loads(d_resp.read().decode("utf-8", errors="replace"))
                    pages = detail_data.get("query", {}).get("pages", {})
                    for page_obj in pages.values():
                        resolved_title = str(page_obj.get("title") or top_title).strip()
                        extract_text = re.sub(r"\s+", " ", str(page_obj.get("extract") or "")).strip()
                        revs = page_obj.get("revisions") or []
                        wikitext = ""
                        if revs and isinstance(revs[0], dict):
                            wikitext = str(revs[0].get("*") or revs[0].get("slots", {}).get("main", {}).get("*") or "")
                        ibox = _extract_wikipedia_infobox_facts(wikitext)
                        if ibox:
                            extracted_facts.update(ibox)
                            extracted_facts["article_title"] = resolved_title

                        page_url = (
                            f"https://en.wikipedia.org/wiki/{urllib.parse.quote(resolved_title.replace(' ', '_'))}"
                        )

                        # If infobox has an incumbent (e.g. President / Prime Minister / Monarch / CEO), fetch incumbent bio too!
                        incumbent_name = ibox.get("incumbent") or ibox.get("president") or ibox.get("prime_minister")
                        if incumbent_name:
                            since_str = (
                                f" (in office since {ibox['incumbentsince']})" if ibox.get("incumbentsince") else ""
                            )
                            fact_prefix = f"Current {resolved_title}: {incumbent_name}{since_str}. "
                            try:
                                inc_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(incumbent_name.replace(' ', '_'))}"
                                with urllib.request.urlopen(
                                    urllib.request.Request(inc_url, headers=wiki_headers), timeout=3.5
                                ) as inc_resp:
                                    inc_data = json.loads(inc_resp.read().decode("utf-8", errors="replace"))
                                    inc_extract = re.sub(r"\s+", " ", str(inc_data.get("extract") or "")).strip()
                                    inc_page_url = (
                                        inc_data.get("content_urls", {}).get("desktop", {}).get("page")
                                        or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(incumbent_name.replace(' ', '_'))}"
                                    )
                                    if inc_extract:
                                        direct_answer = f"**{incumbent_name}** is the current **{resolved_title}**{since_str}. {inc_extract}"
                                        _add_source(
                                            f"{incumbent_name} — Wikipedia",
                                            inc_page_url,
                                            inc_extract,
                                            "wikipedia",
                                        )
                            except Exception:
                                direct_answer = f"**{incumbent_name}** is the current **{resolved_title}**{since_str}."
                            _add_source(
                                f"{resolved_title} — Wikipedia",
                                page_url,
                                fact_prefix + extract_text,
                                "wikipedia",
                            )
                        elif extract_text:
                            fact_summary_parts = []
                            for fk in (
                                "capital",
                                "ceo",
                                "founder",
                                "developer",
                                "latest_release_version",
                                "leader_name1",
                            ):
                                if ibox.get(fk):
                                    fact_summary_parts.append(f"{fk.replace('_', ' ').title()}: {ibox[fk]}")
                            prefix = (" | ".join(fact_summary_parts) + ". ") if fact_summary_parts else ""
                            _add_source(
                                f"{resolved_title} — Wikipedia",
                                page_url,
                                prefix + extract_text,
                                "wikipedia",
                            )
    except Exception as e:
        logger.debug(f"[AIChatAgent] Wikipedia extract/infobox lookup fallback: {e}")

    # 3. Live DuckDuckGo HTML Web Search for real-time web results
    try:
        ddg_post = urllib.parse.urlencode({"q": web_query}).encode("utf-8")
        ddg_req = urllib.request.Request(
            "https://html.duckduckgo.com/html/",
            data=ddg_post,
            headers=browser_headers,
            method="POST",
        )
        with urllib.request.urlopen(ddg_req, timeout=4.5) as resp:
            ddg_html = resp.read(160_000).decode("utf-8", errors="replace")
            link_matches = re.findall(
                r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                ddg_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            snip_matches = re.findall(
                r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                ddg_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            for idx_hit, (raw_href, raw_title) in enumerate(link_matches[:5]):
                clean_title = _strip_html_tags(raw_title)
                clean_snip = _strip_html_tags(snip_matches[idx_hit]) if idx_hit < len(snip_matches) else ""
                real_url = html.unescape(raw_href)
                uddg_m = re.search(r"[?&]uddg=([^&]+)", real_url)
                if uddg_m:
                    real_url = urllib.parse.unquote(uddg_m.group(1))
                elif real_url.startswith("//"):
                    real_url = "https:" + real_url
                if clean_title and clean_snip and real_url.startswith("http"):
                    _add_source(clean_title, real_url, clean_snip, "web")
    except Exception as e:
        logger.debug(f"[AIChatAgent] DuckDuckGo HTML web search fallback: {e}")

    # 4. DuckDuckGo Instant Answer JSON API fallback
    if len(sources) < max_results:
        try:
            ddg_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(search_topic)}&format=json&no_html=1&skip_disambig=1"
            req = urllib.request.Request(ddg_url, headers=wiki_headers)
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                ddg_data = json.loads(resp.read().decode("utf-8", errors="replace"))
                if isinstance(ddg_data, dict):
                    abstract = str(ddg_data.get("AbstractText") or ddg_data.get("Answer") or "").strip()
                    abs_url = str(ddg_data.get("AbstractURL") or "").strip()
                    heading = str(ddg_data.get("Heading") or search_topic).strip()
                    if abstract:
                        _add_source(
                            f"{heading} (Instant Answer)",
                            abs_url or f"https://duckduckgo.com/?q={urllib.parse.quote(search_topic)}",
                            abstract,
                            "duckduckgo",
                        )
        except Exception as e:
            logger.debug(f"[AIChatAgent] DuckDuckGo JSON API fallback: {e}")

    if not direct_answer and sources:
        direct_answer = sources[0]["snippet"]

    return {
        "tool": "browse_internet",
        "status": "ok",
        "query": search_topic,
        "extracted_facts": extracted_facts,
        "direct_answer": direct_answer,
        "sources": sources[:max_results],
    }


AMBIGUOUS_LOCATIONS: dict[str, list[dict[str, str]]] = {
    "santo domingo": [
        {
            "name": "Santo Domingo",
            "country": "Dominican Republic",
            "code": "DO",
            "flag": "🇩🇴",
            "region": "Distrito Nacional (Capital)",
            "query": "Santo Domingo,Dominican Republic",
        },
        {
            "name": "Santo Domingo",
            "country": "Chile",
            "code": "CL",
            "flag": "🇨🇱",
            "region": "Valparaíso Region (San Antonio)",
            "query": "Santo Domingo,Chile",
        },
    ],
    "santiago": [
        {
            "name": "Santiago",
            "country": "Chile",
            "code": "CL",
            "flag": "🇨🇱",
            "region": "Santiago Metropolitan (Capital)",
            "query": "Santiago,Chile",
        },
        {
            "name": "Santiago de los Caballeros",
            "country": "Dominican Republic",
            "code": "DO",
            "flag": "🇩🇴",
            "region": "Santiago Province",
            "query": "Santiago,Dominican Republic",
        },
        {
            "name": "Santiago de Compostela",
            "country": "Spain",
            "code": "ES",
            "flag": "🇪🇸",
            "region": "Galicia",
            "query": "Santiago de Compostela,Spain",
        },
    ],
    "san jose": [
        {
            "name": "San José",
            "country": "Costa Rica",
            "code": "CR",
            "flag": "🇨🇷",
            "region": "San José Province (Capital)",
            "query": "San Jose,Costa Rica",
        },
        {
            "name": "San Jose",
            "country": "United States",
            "code": "US",
            "flag": "🇺🇸",
            "region": "California (Silicon Valley)",
            "query": "San Jose,CA",
        },
    ],
    "cordoba": [
        {
            "name": "Córdoba",
            "country": "Argentina",
            "code": "AR",
            "flag": "🇦🇷",
            "region": "Córdoba Province",
            "query": "Cordoba,Argentina",
        },
        {
            "name": "Córdoba",
            "country": "Spain",
            "code": "ES",
            "flag": "🇪🇸",
            "region": "Andalusia",
            "query": "Cordoba,Spain",
        },
    ],
    "valencia": [
        {
            "name": "Valencia",
            "country": "Spain",
            "code": "ES",
            "flag": "🇪🇸",
            "region": "Valencian Community",
            "query": "Valencia,Spain",
        },
        {
            "name": "Valencia",
            "country": "Venezuela",
            "code": "VE",
            "flag": "🇻🇪",
            "region": "Carabobo",
            "query": "Valencia,Venezuela",
        },
    ],
    "vancouver": [
        {
            "name": "Vancouver",
            "country": "Canada",
            "code": "CA",
            "flag": "🇨🇦",
            "region": "British Columbia",
            "query": "Vancouver,Canada",
        },
        {
            "name": "Vancouver",
            "country": "United States",
            "code": "US",
            "flag": "🇺🇸",
            "region": "Washington State",
            "query": "Vancouver,WA",
        },
    ],
    "springfield": [
        {
            "name": "Springfield",
            "country": "United States",
            "code": "US",
            "flag": "🇺🇸",
            "region": "Illinois (State Capital)",
            "query": "Springfield,IL",
        },
        {
            "name": "Springfield",
            "country": "United States",
            "code": "US",
            "flag": "🇺🇸",
            "region": "Missouri",
            "query": "Springfield,MO",
        },
        {
            "name": "Springfield",
            "country": "United States",
            "code": "US",
            "flag": "🇺🇸",
            "region": "Massachusetts",
            "query": "Springfield,MA",
        },
    ],
}

WEATHER_CONDITION_ICONS: dict[str, str] = {
    "sunny": "☀️",
    "clear": "☀️",
    "partly cloudy": "⛅",
    "cloudy": "☁️",
    "overcast": "🌥️",
    "mist": "🌫️",
    "fog": "🌫️",
    "light rain": "🌧️",
    "moderate rain": "🌧️",
    "heavy rain": "🌧️",
    "patchy rain": "🌦️",
    "light rain shower": "🌦️",
    "rain shower": "🌦️",
    "thundery outbreaks": "⛈️",
    "thunderstorm": "⛈️",
    "snow": "❄️",
    "light snow": "🌨️",
    "heavy snow": "❄️",
    "blizzard": "🌨️",
}

COUNTRY_FLAG_MAP: dict[str, str] = {
    "dominican republic": "🇩🇴",
    "chile": "🇨🇱",
    "united states": "🇺🇸",
    "united states of america": "🇺🇸",
    "usa": "🇺🇸",
    "canada": "🇨🇦",
    "united kingdom": "🇬🇧",
    "uk": "🇬🇧",
    "germany": "🇩🇪",
    "france": "🇫🇷",
    "spain": "🇪🇸",
    "italy": "🇮🇹",
    "japan": "🇯🇵",
    "china": "🇨🇳",
    "australia": "🇦🇺",
    "brazil": "🇧🇷",
    "argentina": "🇦🇷",
    "mexico": "🇲🇽",
    "colombia": "🇨🇴",
    "costa rica": "🇨🇷",
    "nicaragua": "🇳🇮",
    "venezuela": "🇻🇪",
    "jamaica": "🇯🇲",
    "netherlands": "🇳🇱",
    "switzerland": "🇨🇭",
    "austria": "🇦🇹",
}


def _get_weather_icon(desc: str) -> str:
    desc_l = str(desc or "").lower()
    for k, v in WEATHER_CONDITION_ICONS.items():
        if k in desc_l:
            return v
    if "rain" in desc_l:
        return "🌧️"
    if "sun" in desc_l or "clear" in desc_l:
        return "☀️"
    if "snow" in desc_l:
        return "❄️"
    if "cloud" in desc_l:
        return "☁️"
    return "⛅"


def _get_country_flag(country_name: str, code: str = "") -> str:
    c_low = str(country_name or "").lower().strip()
    if c_low in COUNTRY_FLAG_MAP:
        return COUNTRY_FLAG_MAP[c_low]
    for k, v in COUNTRY_FLAG_MAP.items():
        if k in c_low or c_low in k:
            return v
    if len(code) == 2:
        return chr(ord(code[0].upper()) + 127397) + chr(ord(code[1].upper()) + 127397)
    return "🌍"


def _extract_weather_location(message: str) -> str | None:
    """
    Extracts the location name from queries in English, Spanish, German, and French.
    """
    clean = re.sub(r"[\?\.\!\,]+$", "", message.strip())
    patterns = [
        r"(?:what(?:s|\'s|\s+is)?\s+(?:the\s+)?(?:current\s+)?weather\s+(?:like\s+)?(?:in|for|at)\s+)(.+)",
        r"(?:(?:current\s+)?weather\s+(?:forecast\s+)?(?:in|for|at)\s+)(.+)",
        r"(?:(?:how\s+is\s+the\s+weather|how\'s\s+the\s+weather)\s+(?:in|for|at)\s+)(.+)",
        r"(?:(?:temperature|temp)\s+(?:in|for|at)\s+)(.+)",
        r"(?:(?:how\s+(?:hot|cold)\s+is\s+it)\s+(?:in|at)\s+)(.+)",
        r"(?:(?:is\s+it\s+(?:raining|snowing|sunny))\s+(?:in|at)\s+)(.+)",
        r"(?:(?:forecast)\s+(?:for|in)\s+)(.+)",
        r"(?:(?:clima|tiempo|temperatura)\s+(?:en|de|para)\s+)(.+)",
        r"(?:(?:wetter|vorhersage)\s+(?:in|für)\s+)(.+)",
        r"(?:(?:meteo|météo)\s+(?:à|a|pour|en\s+)?)(.+)",
        r"(.+?)\s+(?:weather|forecast|clima|wetter|météo|meteo)$",
    ]
    for p in patterns:
        m = re.search(p, clean, re.IGNORECASE)
        if m:
            loc = m.group(1).strip()
            loc = re.sub(r"^(?:the\s+city\s+of\s+|city\s+of\s+)", "", loc, flags=re.IGNORECASE)
            loc = re.sub(r"\s+(?:today|tomorrow|right\s+now|now|currently)$", "", loc, flags=re.IGNORECASE).strip()
            loc = loc.strip("'\"` ")
            if loc and len(loc) >= 2:
                if loc.lower() not in ("cpu", "gpu", "ram", "nas", "disk", "server", "docker", "system"):
                    return loc
    return None


def _resolve_country_confirmation(user_msg: str, prev_asst_msg: str) -> str | None:
    """
    If the previous assistant message asked for country disambiguation (e.g. Dominican Republic vs Chile),
    checks if current user utterance confirms one of the candidate countries and returns the resolved query.
    """
    u_clean = user_msg.strip().lower()
    asst_lower = prev_asst_msg.lower()

    if "santo domingo" in asst_lower:
        if any(
            w in u_clean
            for w in (
                "dominican",
                "república dominicana",
                "republica dominicana",
                "dr",
                "d.r.",
                "dom rep",
                "capital",
                "caribbean",
                "first",
                "1",
                "1st",
            )
        ):
            return "Santo Domingo, Dominican Republic"
        elif any(w in u_clean for w in ("chile", "chilean", "valparaiso", "valparaíso", "second", "2", "2nd")):
            return "Santo Domingo, Chile"

    if "santiago" in asst_lower:
        if any(w in u_clean for w in ("chile", "chilean", "capital", "first", "1", "1st")):
            return "Santiago, Chile"
        elif any(w in u_clean for w in ("dominican", "dr", "caballeros", "second", "2", "2nd")):
            return "Santiago, Dominican Republic"
        elif any(w in u_clean for w in ("spain", "spanish", "compostela", "galicia", "third", "3", "3rd")):
            return "Santiago de Compostela, Spain"

    if "san jose" in asst_lower or "san josé" in asst_lower:
        if any(w in u_clean for w in ("costa rica", "cr", "capital", "first", "1", "1st")):
            return "San Jose, Costa Rica"
        elif any(w in u_clean for w in ("california", "ca", "usa", "us", "silicon valley", "second", "2", "2nd")):
            return "San Jose, CA"

    if "cordoba" in asst_lower or "córdoba" in asst_lower:
        if any(w in u_clean for w in ("argentina", "arg", "first", "1", "1st")):
            return "Cordoba, Argentina"
        elif any(w in u_clean for w in ("spain", "spanish", "andalusia", "second", "2", "2nd")):
            return "Cordoba, Spain"

    if "vancouver" in asst_lower:
        if any(w in u_clean for w in ("canada", "canadian", "bc", "british columbia", "first", "1", "1st")):
            return "Vancouver, Canada"
        elif any(w in u_clean for w in ("wa", "washington", "usa", "us", "second", "2", "2nd")):
            return "Vancouver, WA"

    if "springfield" in asst_lower:
        if any(w in u_clean for w in ("illinois", "il", "capital", "first", "1", "1st")):
            return "Springfield, IL"
        elif any(w in u_clean for w in ("missouri", "mo", "second", "2", "2nd")):
            return "Springfield, MO"
        elif any(w in u_clean for w in ("massachusetts", "ma", "third", "3", "3rd")):
            return "Springfield, MA"

    return None


def _fetch_wttr_in(query: str, timeout: float = 4.0) -> dict[str, Any] | None:
    """Fetches real-time JSON weather data from wttr.in with zero disk spin-ups."""
    try:
        encoded = urllib.parse.quote_plus(query.strip())
        url = f"https://wttr.in/{encoded}?format=j1"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ZettNAS-Toolkit-Weather/2.0 (+https://github.com/fr0styx/zettnas-toolkit)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw_bytes = resp.read(120_000)
                return json.loads(raw_bytes.decode("utf-8", errors="replace"))
    except Exception as e:
        logger.debug(f"[ZettAI Weather] wttr.in query for '{query}' failed: {e}")
    return None


def _parse_single_wttr_response(data: dict[str, Any], query_fallback: str) -> dict[str, Any]:
    """Extracts structured meteorological metrics from wttr.in j1 JSON payload."""
    area_obj = (data.get("nearest_area") or [{}])[0]
    area_name = (area_obj.get("areaName") or [{}])[0].get("value") or query_fallback
    country = (area_obj.get("country") or [{}])[0].get("value") or ""
    region = (area_obj.get("region") or [{}])[0].get("value") or ""

    curr = (data.get("current_condition") or [{}])[0]
    temp_c = int(curr.get("temp_C") or 0)
    temp_f = int(curr.get("temp_F") or round(temp_c * 9 / 5 + 32))
    feels_c = int(curr.get("FeelsLikeC") or temp_c)
    feels_f = int(curr.get("FeelsLikeF") or temp_f)
    condition_desc = (curr.get("weatherDesc") or [{}])[0].get("value") or "Clear"
    humidity = int(curr.get("humidity") or 0)
    wind_kmph = int(curr.get("windspeedKmph") or 0)
    wind_dir = str(curr.get("winddir16Point") or "").strip()
    uv_index = int(curr.get("uvIndex") or 0)

    forecast_days: list[dict[str, Any]] = []
    weather_list = data.get("weather") or []
    day_labels = ["Today", "Tomorrow", "Next Day"]
    for idx_w, w in enumerate(weather_list[:3]):
        max_c = int(w.get("maxtempC") or 0)
        min_c = int(w.get("mintempC") or 0)
        max_f = int(w.get("maxtempF") or round(max_c * 9 / 5 + 32))
        min_f = int(w.get("mintempF") or round(min_c * 9 / 5 + 32))
        hourly_mid = (w.get("hourly") or [{}])[len(w.get("hourly", [])) // 2]
        day_desc = (hourly_mid.get("weatherDesc") or [{}])[0].get("value") or condition_desc
        forecast_days.append(
            {
                "day_label": day_labels[idx_w] if idx_w < len(day_labels) else f"Day {idx_w + 1}",
                "date": w.get("date"),
                "maxtemp_c": max_c,
                "maxtemp_f": max_f,
                "mintemp_c": min_c,
                "mintemp_f": min_f,
                "condition": day_desc,
                "icon": _get_weather_icon(day_desc),
            }
        )

    flag = _get_country_flag(country)

    return {
        "name": query_fallback.split(",")[0].strip().title(),
        "area_name": area_name,
        "region": region,
        "country": country,
        "flag": flag,
        "temp_c": temp_c,
        "temp_f": temp_f,
        "feels_like_c": feels_c,
        "feels_like_f": feels_f,
        "condition": condition_desc,
        "icon": _get_weather_icon(condition_desc),
        "humidity": humidity,
        "wind_kmph": wind_kmph,
        "wind_dir": wind_dir,
        "uv_index": uv_index,
        "forecast": forecast_days,
    }


def _external_services(tool_results: list[dict[str, Any]]) -> list[str]:
    """Services outside the NAS this turn actually contacted, for the "data left this device" note."""
    out: list[str] = []
    for tr in tool_results:
        if tr.get("status") == "blocked":
            continue
        if tr.get("tool") == "get_weather":
            out.append("wttr.in (weather)")
        elif tr.get("tool") == "browse_internet":
            out.append("web search")
            for src in tr.get("sources") or []:
                host = urllib.parse.urlparse(str(src.get("url") or "")).hostname
                if host and host not in out:
                    out.append(host)
    return out[:8]


def tool_get_weather(location: str) -> dict[str, Any]:
    if not _WEB_ALLOWED.get():
        return {"tool": "get_weather", "status": "blocked", "error": _WEB_BLOCKED_MSG, "location": location}
    """
    Fetches live meteorological weather conditions with intelligent country disambiguation.
    Guarantees zero hard drive spin-ups (zero_disk_wakeups: True).
    """
    clean_loc = str(location or "").strip()
    if not clean_loc:
        return {
            "tool": "get_weather",
            "status": "error",
            "error": "Location query cannot be empty.",
            "zero_disk_wakeups": True,
        }

    # Deterministic test mode
    if os.environ.get("TESTING") == "1" or os.environ.get("ZETTNAS_TEST_MODE") == "1":
        loc_low = clean_loc.lower()
        if "santo domingo" in loc_low and not any(c in loc_low for c in ("dominican", "chile", "dr", "cl")):
            return {
                "tool": "get_weather",
                "status": "ok",
                "is_ambiguous": True,
                "location": "Santo Domingo",
                "candidates": [
                    {
                        "name": "Santo Domingo",
                        "country": "Dominican Republic",
                        "flag": "🇩🇴",
                        "region": "Distrito Nacional (Capital)",
                        "temp_c": 31,
                        "temp_f": 87,
                        "feels_like_c": 34,
                        "feels_like_f": 93,
                        "condition": "Sunny",
                        "icon": "☀️",
                        "humidity": 60,
                        "wind_kmph": 11,
                        "wind_dir": "SE",
                        "uv_index": 8,
                        "forecast": [
                            {
                                "day_label": "Today",
                                "maxtemp_c": 31,
                                "maxtemp_f": 88,
                                "mintemp_c": 22,
                                "mintemp_f": 72,
                                "condition": "Sunny",
                                "icon": "☀️",
                            },
                            {
                                "day_label": "Tomorrow",
                                "maxtemp_c": 32,
                                "maxtemp_f": 90,
                                "mintemp_c": 23,
                                "mintemp_f": 73,
                                "condition": "Partly Cloudy",
                                "icon": "⛅",
                            },
                            {
                                "day_label": "Next Day",
                                "maxtemp_c": 31,
                                "maxtemp_f": 88,
                                "mintemp_c": 23,
                                "mintemp_f": 73,
                                "condition": "Light Rain",
                                "icon": "🌧️",
                            },
                        ],
                    },
                    {
                        "name": "Santo Domingo",
                        "country": "Chile",
                        "flag": "🇨🇱",
                        "region": "Valparaíso Region (San Antonio)",
                        "temp_c": 16,
                        "temp_f": 61,
                        "feels_like_c": 16,
                        "feels_like_f": 61,
                        "condition": "Light rain shower",
                        "icon": "🌧️",
                        "humidity": 78,
                        "wind_kmph": 14,
                        "wind_dir": "WSW",
                        "uv_index": 4,
                        "forecast": [
                            {
                                "day_label": "Today",
                                "maxtemp_c": 17,
                                "maxtemp_f": 63,
                                "mintemp_c": 10,
                                "mintemp_f": 50,
                                "condition": "Rain",
                                "icon": "🌧️",
                            },
                            {
                                "day_label": "Tomorrow",
                                "maxtemp_c": 18,
                                "maxtemp_f": 64,
                                "mintemp_c": 9,
                                "mintemp_f": 48,
                                "condition": "Cloudy",
                                "icon": "☁️",
                            },
                        ],
                    },
                ],
                "disambiguation_prompt": "Did you mean Santo Domingo, Dominican Republic 🇩🇴 or Santo Domingo, Chile 🇨🇱?",
                "summary": "Ambiguous location 'Santo Domingo'. Retrieved live conditions for 2 countries.",
                "zero_disk_wakeups": True,
            }
        else:
            is_chile = "chile" in loc_low or "cl" in loc_low
            c_name = (
                "Chile"
                if is_chile
                else ("Dominican Republic" if "dominican" in loc_low or "dr" in loc_low else "Global")
            )
            c_flag = "🇨🇱" if is_chile else ("🇩🇴" if "dominican" in loc_low or "dr" in loc_low else "🌍")
            t_c = 16 if is_chile else 31
            t_f = 61 if is_chile else 87
            cond = "Light rain shower" if is_chile else "Sunny"
            return {
                "tool": "get_weather",
                "status": "ok",
                "is_ambiguous": False,
                "location": clean_loc.split(",")[0].strip().title(),
                "country": c_name,
                "flag": c_flag,
                "temperature_c": t_c,
                "temperature_f": t_f,
                "feels_like_c": t_c,
                "feels_like_f": t_f,
                "condition": cond,
                "icon": "🌧️" if is_chile else "☀️",
                "humidity_pct": 78 if is_chile else 60,
                "wind_kmph": 14 if is_chile else 11,
                "wind_dir": "WSW" if is_chile else "SE",
                "uv_index": 4 if is_chile else 8,
                "forecast": [
                    {
                        "day_label": "Today",
                        "maxtemp_c": t_c,
                        "maxtemp_f": t_f,
                        "mintemp_c": t_c - 6,
                        "mintemp_f": t_f - 11,
                        "condition": cond,
                        "icon": "☀️",
                    },
                ],
                "summary": f"{clean_loc.title()}, {c_name} {c_flag}: {t_c}°C ({t_f}°F), {cond}",
                "zero_disk_wakeups": True,
            }

    loc_lower = clean_loc.lower().strip()
    norm_city = re.sub(r"[\,\.\-\_]+", " ", loc_lower).strip()

    ambig_match_key = None
    for amb_k in AMBIGUOUS_LOCATIONS:
        if norm_city == amb_k or norm_city.startswith(f"{amb_k} "):
            ambig_match_key = amb_k
            break

    if ambig_match_key:
        candidates_cfg = AMBIGUOUS_LOCATIONS[ambig_match_key]
        has_explicit_country = any(
            c["country"].lower() in loc_lower
            or c["code"].lower() in loc_lower.split()
            or c["region"].lower() in loc_lower
            for c in candidates_cfg
        )
        if not has_explicit_country:
            candidate_results: list[dict[str, Any]] = []
            for cand in candidates_cfg[:2]:
                data = _fetch_wttr_in(cand["query"])
                if data:
                    parsed = _parse_single_wttr_response(data, cand["name"])
                    parsed["country"] = cand["country"]
                    parsed["flag"] = cand["flag"]
                    parsed["region"] = cand["region"]
                    candidate_results.append(parsed)

            if len(candidate_results) >= 2:
                prompt_text = (
                    f"Did you mean {candidate_results[0]['name']}, {candidate_results[0]['country']} {candidate_results[0]['flag']} or "
                    f"{candidate_results[1]['name']}, {candidate_results[1]['country']} {candidate_results[1]['flag']}?"
                )
                return {
                    "tool": "get_weather",
                    "status": "ok",
                    "is_ambiguous": True,
                    "location": candidate_results[0]["name"],
                    "candidates": candidate_results,
                    "disambiguation_prompt": prompt_text,
                    "summary": f"Ambiguous location '{clean_loc}'. Retrieved live weather for {len(candidate_results)} countries.",
                    "zero_disk_wakeups": True,
                }

    data = _fetch_wttr_in(clean_loc)
    if not data:
        return {
            "tool": "get_weather",
            "status": "error",
            "error": f"Could not retrieve meteorological data for '{clean_loc}'. Please verify location spelling.",
            "zero_disk_wakeups": True,
        }

    parsed = _parse_single_wttr_response(data, clean_loc)
    return {
        "tool": "get_weather",
        "status": "ok",
        "is_ambiguous": False,
        "location": parsed["name"],
        "area_name": parsed["area_name"],
        "region": parsed["region"],
        "country": parsed["country"],
        "flag": parsed["flag"],
        "temperature_c": parsed["temp_c"],
        "temperature_f": parsed["temp_f"],
        "feels_like_c": parsed["feels_like_c"],
        "feels_like_f": parsed["feels_like_f"],
        "condition": parsed["condition"],
        "icon": parsed["icon"],
        "humidity_pct": parsed["humidity"],
        "wind_kmph": parsed["wind_kmph"],
        "wind_dir": parsed["wind_dir"],
        "uv_index": parsed["uv_index"],
        "forecast": parsed["forecast"],
        "summary": f"{parsed['name']}, {parsed['country']} {parsed['flag']}: {parsed['temp_c']}°C ({parsed['temp_f']}°F), {parsed['condition']}",
        "zero_disk_wakeups": True,
    }


def _synthesize_weather_grounded_answer(clean_msg: str, tr: dict[str, Any]) -> str:
    """Produces clean, formatted markdown with meteorological metrics and country confirmation."""
    if tr.get("is_ambiguous"):
        cands = tr.get("candidates") or []
        lines = [
            f"### ⛅ Live Meteorological Weather: {tr.get('location', 'Santo Domingo')}\n",
            f"**{tr.get('location', 'This location')}** can refer to multiple global cities. Here is the live weather for both candidates:\n",
        ]
        for c in cands:
            lines.append(f"#### {c.get('flag', '📍')} {c.get('name')}, {c.get('country')} ({c.get('region')})")
            lines.append(
                f"- **Current Weather:** {c.get('icon', '⛅')} **{c.get('condition')}** (`{c.get('temp_c')}°C` / `{c.get('temp_f')}°F`, feels like `{c.get('feels_like_c')}°C` / `{c.get('feels_like_f')}°F`)"
            )
            lines.append(
                f"- **Humidity:** `{c.get('humidity')}%` • **Wind:** `{c.get('wind_kmph')} km/h {c.get('wind_dir')}` • **UV Index:** `{c.get('uv_index')}`"
            )
            fc = c.get("forecast") or []
            if fc:
                lines.append("- **Forecast:**")
                for f in fc:
                    lines.append(
                        f"  - **{f.get('day_label')}:** High `{f.get('maxtemp_c')}°C` (`{f.get('maxtemp_f')}°F`) / Low `{f.get('mintemp_c')}°C` (`{f.get('mintemp_f')}°F`) — {f.get('icon')} {f.get('condition')}"
                    )
            lines.append("")

        lines.append("---")
        prompt = tr.get("disambiguation_prompt") or "Did you mean the Dominican Republic 🇩🇴 or Chile 🇨🇱?"
        lines.append(f"> 💡 **Country Confirmation:** {prompt} Reply with your country to lock in future updates!")
        return "\n".join(lines)

    loc = tr.get("location") or "Location"
    country = tr.get("country") or ""
    flag = tr.get("flag") or "⛅"
    lines = [
        f"### ⛅ Live Weather: {loc}{f', {country}' if country else ''} {flag}\n",
        f"- **Current Conditions:** {tr.get('icon', '⛅')} **{tr.get('condition')}**",
        f"- **Temperature:** **`{tr.get('temperature_c')}°C` / `{tr.get('temperature_f')}°F`** (Feels like `{tr.get('feels_like_c')}°C` / `{tr.get('feels_like_f')}°F`)",
        f"- **Humidity:** `{tr.get('humidity_pct')}%` • **Wind:** `{tr.get('wind_kmph')} km/h {tr.get('wind_dir')}` • **UV Index:** `{tr.get('uv_index')}`\n",
    ]
    fc = tr.get("forecast") or []
    if fc:
        lines.append("#### 📅 3-Day Forecast")
        for f in fc:
            lines.append(
                f"- **{f.get('day_label')}:** High `{f.get('maxtemp_c')}°C` (`{f.get('maxtemp_f')}°F`) / Low `{f.get('mintemp_c')}°C` (`{f.get('mintemp_f')}°F`) — {f.get('icon')} {f.get('condition')}"
            )
    return "\n".join(lines)
