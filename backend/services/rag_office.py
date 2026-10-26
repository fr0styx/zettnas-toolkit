"""Text from office documents, e-books and e-mail for the AI index (AI-9).

Standard library only: these formats are ZIP files of XML (Office Open XML, OpenDocument,
EPUB) or MIME text (e-mail). Every member read is capped like the DOCX reader, so a small file
cannot expand into gigabytes.
"""

import email
import email.policy
import html.parser
import mailbox
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

from backend.config import logger
from backend.logging_config import sanitize_string


class _HTMLTextExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self._Parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag.lower() in ("script", "style", "noscript"):
            self._skip = True
        elif tag.lower() in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"):
            self._Parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip and data:
            self._Parts.append(data)

    def get_text(self) -> str:
        return "".join(self._Parts)


MAX_MEMBER_BYTES = 64 * 1024 * 1024  # one XML part, uncompressed
MAX_TOTAL_BYTES = 128 * 1024 * 1024  # all parts of one file, uncompressed
MAX_TEXT_CHARS = 4_000_000
MAX_MBOX_MESSAGES = 2000

OFFICE_EXTENSIONS = {".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub", ".eml", ".mbox", ".rtf"}


class _Budget:
    def __init__(self) -> None:
        self.left = MAX_TOTAL_BYTES

    def read(self, zf: zipfile.ZipFile, name: str) -> bytes | None:
        try:
            info = zf.getinfo(name)
        except KeyError:
            return None
        if info.file_size > MAX_MEMBER_BYTES or info.file_size > self.left:
            return None
        with zf.open(info) as f:
            data = f.read(MAX_MEMBER_BYTES + 1)
        if len(data) > MAX_MEMBER_BYTES:
            return None
        self.left -= len(data)
        return data


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml(data: bytes | None) -> ET.Element | None:
    if not data:
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


def _xlsx(zf: zipfile.ZipFile, b: _Budget) -> str:
    shared: list[str] = []
    root = _xml(b.read(zf, "xl/sharedStrings.xml"))
    if root is not None:
        for si in root:
            shared.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"))
    names = {}
    wb = _xml(b.read(zf, "xl/workbook.xml"))
    if wb is not None:
        for i, sh in enumerate(x for x in wb.iter() if _local(x.tag) == "sheet"):
            names[f"xl/worksheets/sheet{i + 1}.xml"] = sh.get("name") or f"Sheet {i + 1}"
    out = []
    for name in sorted(n for n in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)):
        sheet = _xml(b.read(zf, name))
        if sheet is None:
            continue
        out.append(f"## {names.get(name, name.rsplit('/', 1)[-1])}")
        for row in (r for r in sheet.iter() if _local(r.tag) == "row"):
            cells = []
            for c in (x for x in row if _local(x.tag) == "c"):
                v = next((x.text for x in c if _local(x.tag) == "v"), None)
                if c.get("t") == "s" and v is not None and v.isdigit() and int(v) < len(shared):
                    v = shared[int(v)]
                elif c.get("t") == "inlineStr":
                    v = "".join(t.text or "" for t in c.iter() if _local(t.tag) == "t")
                if v not in (None, ""):
                    cells.append(str(v))
            if cells:
                out.append(" | ".join(cells))
    return "\n".join(out)


def _pptx(zf: zipfile.ZipFile, b: _Budget) -> str:
    def num(n: str) -> int:
        m = re.search(r"(\d+)\.xml$", n)
        return int(m.group(1)) if m else 0

    out = []
    for name in sorted(
        (n for n in zf.namelist() if re.match(r"ppt/(slides/slide|notesSlides/notesSlide)\d+\.xml$", n)),
        key=lambda n: (("notes" in n), num(n)),
    ):
        root = _xml(b.read(zf, name))
        if root is None:
            continue
        paras = []
        for p in (x for x in root.iter() if _local(x.tag) == "p"):
            line = "".join(t.text or "" for t in p.iter() if _local(t.tag) == "t").strip()
            if line:
                paras.append(line)
        if paras:
            out.append(("## Notes " if "notes" in name else "## Slide ") + str(num(name)))
            out.extend(paras)
    return "\n".join(out)


def _odf(zf: zipfile.ZipFile, b: _Budget) -> str:
    root = _xml(b.read(zf, "content.xml"))
    if root is None:
        return ""
    out = []
    for el in root.iter():
        tag = _local(el.tag)
        if tag in ("h", "p"):
            line = "".join(el.itertext()).strip()
            if line:
                out.append(("# " if tag == "h" else "") + line)
        elif tag == "table-row":
            cells = ["".join(c.itertext()).strip() for c in el if _local(c.tag) == "table-cell"]
            cells = [c for c in cells if c]
            if cells:
                out.append(" | ".join(cells))
    # table cells also hold <text:p>; keep the row form and drop the duplicate paragraphs
    seen, uniq = set(), []
    for line in out:
        if line not in seen:
            uniq.append(line)
            seen.add(line)
    return "\n".join(uniq)


def _epub(zf: zipfile.ZipFile, b: _Budget) -> str:
    container = _xml(b.read(zf, "META-INF/container.xml"))
    opf_path = None
    if container is not None:
        rf = next((x for x in container.iter() if _local(x.tag) == "rootfile"), None)
        opf_path = rf.get("full-path") if rf is not None else None
    opf = _xml(b.read(zf, opf_path)) if opf_path else None
    if opf is None:
        return ""
    base = posixpath.dirname(opf_path or "")
    meta = []
    for x in opf.iter():
        value = (x.text or "").strip()
        if _local(x.tag) in ("title", "creator") and value:
            meta.append(f"{_local(x.tag).capitalize()}: {value}")
    items = {x.get("id"): x.get("href") for x in opf.iter() if _local(x.tag) == "item"}
    spine = [items.get(x.get("idref")) for x in opf.iter() if _local(x.tag) == "itemref"]
    out = list(meta)
    for href in spine:
        if not href:
            continue
        data = b.read(zf, posixpath.normpath(posixpath.join(base, href)))
        if not data:
            continue
        ex = _HTMLTextExtractor()
        try:
            ex.feed(data.decode("utf-8", errors="ignore"))
        except Exception:
            continue
        text = re.sub(r"\n{3,}", "\n\n", ex.get_text()).strip()
        if text:
            out.append(text)
        if sum(len(t) for t in out) > MAX_TEXT_CHARS:
            break
    return "\n\n".join(out)


def _message_text(msg: Any) -> str:
    head = []
    for h in ("Subject", "From", "To", "Cc", "Date"):
        v = msg.get(h)
        if v:
            head.append(f"{h}: {v}")
    body, html_body, attachments = [], [], []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.is_multipart():
            continue
        fname = part.get_filename()
        if fname:
            attachments.append(fname)
            continue
        ctype = part.get_content_type()
        try:
            payload = part.get_content()
        except Exception:
            raw = part.get_payload(decode=True) or b""
            payload = raw.decode(part.get_content_charset() or "utf-8", errors="ignore")
        if not isinstance(payload, str):
            continue
        if ctype == "text/plain":
            body.append(payload)
        elif ctype == "text/html":
            ex = _HTMLTextExtractor()
            ex.feed(payload)
            html_body.append(ex.get_text())
    text = "\n".join(body) if body else "\n".join(html_body)
    if attachments:
        head.append("Attachments: " + ", ".join(attachments))
    return "\n".join(head) + "\n\n" + re.sub(r"\n{3,}", "\n\n", text).strip()


def _rtf(raw: str) -> str:
    # enough RTF to read the words: drop groups that hold no text, control words and braces
    text = re.sub(r"\{\\\*[^{}]*\}|\{\\(?:fonttbl|colortbl|stylesheet|info)[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "", raw)
    text = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", errors="ignore"), text)
    text = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), text)
    text = re.sub(r"\\(?:par|line)\b ?", "\n", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?|\\[^a-zA-Z]|[{}]", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_office_text(file_path: str, ext: str) -> str:
    """Plain text of an .xlsx, .pptx, .odt/.ods/.odp, .epub, .eml, .mbox or .rtf file; "" when
    it cannot be read."""
    ext = ext.lower()
    try:
        if ext in (".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub"):
            with zipfile.ZipFile(file_path) as zf:
                b = _Budget()
                if ext == ".xlsx":
                    text = _xlsx(zf, b)
                elif ext == ".pptx":
                    text = _pptx(zf, b)
                elif ext == ".epub":
                    text = _epub(zf, b)
                else:
                    text = _odf(zf, b)
            return text[:MAX_TEXT_CHARS]
        if ext == ".eml":
            with open(file_path, "rb") as f:
                msg = email.message_from_binary_file(f, policy=email.policy.default)
            return _message_text(msg)[:MAX_TEXT_CHARS]
        if ext == ".mbox":
            parts = []
            box = mailbox.mbox(file_path, create=False)
            try:
                for i, key in enumerate(box.iterkeys()):
                    raw = box.get_bytes(key)
                    msg = email.message_from_bytes(raw, policy=email.policy.default)
                    if i >= MAX_MBOX_MESSAGES or sum(len(p) for p in parts) > MAX_TEXT_CHARS:
                        break
                    parts.append(_message_text(msg))
            finally:
                box.close()
            return "\n\n---\n\n".join(parts)[:MAX_TEXT_CHARS]
        if ext == ".rtf":
            with open(file_path, "rb") as f:
                return _rtf(f.read(16 * 1024 * 1024).decode("latin-1", errors="ignore"))[:MAX_TEXT_CHARS]
    except Exception as e:
        logger.debug(f"[RAG] {ext} parse error on {sanitize_string(file_path)}: {e}")
    return ""
