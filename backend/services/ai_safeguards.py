"""Safeguards for what ZettAI sends out and what it suggests running (AI-12).

- safe_web_query: a web search carries a short question, not the person's data. Addresses,
  e-mail addresses, file paths, long numbers and keys are removed, and a search the model asks
  for is refused when it repeats text from the person's files (the classic way a prompt hidden
  in a document gets data out).
- compose_risks: what to check in a Compose file before running it.
"""

import re

MAX_WEB_QUERY_CHARS = 200
SHINGLE_WORDS = 6

_SCRUB = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), ""),  # e-mail addresses
    (re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/]*:[^\s/@]*@\S+", re.I), ""),  # URLs with credentials
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), ""),  # IPv4
    (re.compile(r"\b(?:[0-9a-f]{1,4}:){3,7}[0-9a-f]{1,4}\b", re.I), ""),  # IPv6
    (re.compile(r"(?:(?<=\s)|^)(?:/[\w.@~-]+){2,}/?|\b[a-z]:\\[^\s]+", re.I), ""),  # file paths
    (re.compile(r"\b(?:sk|ghp|gho|glpat|xox[bap]|zat)[-_][A-Za-z0-9_-]{8,}\b"), ""),  # API keys and tokens
    (re.compile(r"\b[A-Za-z0-9+/_-]{32,}={0,2}(?![\w/+-])"), ""),  # long opaque strings
    (re.compile(r"(?<![\d.,])\d[\d \-]{6,}\d(?![\d.,])"), ""),  # phone, account and card numbers
]


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", str(text or "").lower())


def safe_web_query(query: str, private_texts: list[str] | tuple[str, ...] = ()) -> tuple[str | None, str]:
    """(query to send, "") or (None, reason it was refused)."""
    q = " ".join(str(query or "").split())
    for pat, repl in _SCRUB:
        q = pat.sub(repl, q)
    q = " ".join(q.split())[:MAX_WEB_QUERY_CHARS].strip(" ,;:-")
    if len(_words(q)) == 0:
        return None, "nothing left to search for once private details were removed"
    words = _words(q)
    if private_texts and len(words) >= SHINGLE_WORDS:
        shingles = {" ".join(words[i : i + SHINGLE_WORDS]) for i in range(len(words) - SHINGLE_WORDS + 1)}
        for text in private_texts:
            w = _words(text)
            if any(" ".join(w[i : i + SHINGLE_WORDS]) in shingles for i in range(max(0, len(w) - SHINGLE_WORDS + 1))):
                return None, "the search repeated text from your files"
    return q, ""


_COMPOSE_CHECKS = [
    (
        re.compile(r"^\s*privileged:\s*true\b", re.M | re.I),
        "runs a container with full access to the host (privileged: true)",
    ),
    (
        re.compile(r"docker\.sock", re.I),
        "gives a container control of Docker itself (docker.sock), which is root on the host",
    ),
    (re.compile(r"^\s*network_mode:\s*[\"']?host\b", re.M | re.I), "shares the host's network (network_mode: host)"),
    (re.compile(r"^\s*pid:\s*[\"']?host\b", re.M | re.I), "sees every process on the host (pid: host)"),
    (re.compile(r"\b(?:SYS_ADMIN|SYS_MODULE|SYS_RAWIO|ALL)\b"), "adds powerful kernel capabilities (cap_add)"),
    (re.compile(r"(?:apparmor|seccomp)[:=]unconfined", re.I), "turns off a security profile (unconfined)"),
    (
        re.compile(r"^\s*-\s*[\"']?/(?:etc|root|boot|proc|sys)?(?::|/:)", re.M),
        "mounts the host's root or system folders",
    ),
    (re.compile(r"/dev/(?:mem|kmsg|sd[a-z]|nvme\d)", re.I), "passes raw disks or kernel memory into the container"),
    (
        re.compile(
            r":-\s*(?:changeme\w*|password|admin|secret|123456)\b|(?:PASSWORD|PASS)[\"']?\s*[:=]\s*[\"']?(?:changeme\w*|password|admin|secret|123456)\b",
            re.I,
        ),
        "contains a default password",
    ),
]


def compose_risks(text: str) -> list[str]:
    """Plain-language list of the risky settings in a Compose file (empty when none)."""
    found = []
    for pat, label in _COMPOSE_CHECKS:
        if pat.search(str(text or "")) and label not in found:
            found.append(label)
    return found


_YAML_BLOCK = re.compile(r"```(?:ya?ml|docker-compose|compose)?\s*\n(.*?)```", re.S | re.I)


def compose_warning_for_reply(reply: str) -> str:
    """A short note to append when a reply contains a Compose file with risky settings."""
    risks: list[str] = []
    for block in _YAML_BLOCK.findall(str(reply or "")):
        if re.search(r"^\s*services:\s*$", block, re.M):
            for r in compose_risks(block):
                if r not in risks:
                    risks.append(r)
    if not risks:
        return ""
    return "\n\n> **Check before running this Compose file:** it " + "; it ".join(risks) + "."
