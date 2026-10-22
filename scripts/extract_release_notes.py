"""Writes RELEASE_NOTES.md and the release title for a tag from CHANGELOG.md.

The notes are everything under "## <tag> ..." up to the next "## v" entry, so the
"####" sections inside an entry are kept. Relative links become links to the tagged files.
"""

import os
import re
import sys


def extract(text: str, tag: str, repo: str = ""):
    m = re.search(rf"^##\s+{re.escape(tag)}\b.*?\n(.*?)(?=^##\s+v\d|\Z)", text, re.DOTALL | re.MULTILINE)
    if not m:
        return tag, ""
    notes = m.group(1).strip()
    notes = re.sub(r"\n-{3,}\s*$", "", notes).strip()
    if repo:
        notes = re.sub(
            r"\]\((?!https?://|#|mailto:)([^)\s]+)\)",
            lambda mm: f"](https://github.com/{repo}/blob/{tag}/{mm.group(1).lstrip('./')})",
            notes,
        )
    title = tag
    first = notes.splitlines()[0].strip() if notes else ""
    if first.startswith("###"):
        clean = re.sub(r"^[^\w\s\(\)]+\s*", "", re.sub(r"^###\s*", "", first)).strip()
        if clean:
            title = f"{tag} - {clean}"
    return title, notes


def main():
    tag = os.environ.get("GITHUB_REF_NAME", "") or (sys.argv[1] if len(sys.argv) > 1 else "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    text = ""
    if os.path.exists("CHANGELOG.md"):
        with open("CHANGELOG.md", encoding="utf-8") as f:
            text = f.read()
    title, notes = extract(text, tag, repo)
    with open("RELEASE_NOTES.md", "w", encoding="utf-8") as out:
        out.write(notes)
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh_out:
        gh_out.write(f"title={title}\n")
    print(title)


if __name__ == "__main__":
    main()
