"""
Vocabulary, file-type lists, tokenisation, query parsing and colour helpers for the AI index.

Split out of rag_engine.py (AI-21), which re-exports these names.
"""

import colorsys
import math
import re
import struct
from typing import Any

EMBEDDING_DIM = 384
MAX_INDEX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB max text/PDF file parse cap

# Canonical 12-Color Perceptual Palette (Peer-Reviewed across UX, ML, and Storage)
CANONICAL_COLORS: tuple[str, ...] = (
    "red",
    "orange",
    "yellow",
    "green",
    "cyan",
    "blue",
    "purple",
    "pink",
    "white",
    "silver",
    "black",
    "brown",
)

COLOR_HEX_MAP: dict[str, str] = {
    "red": "#ef4444",
    "orange": "#f97316",
    "yellow": "#eab308",
    "green": "#22c55e",
    "cyan": "#06b6d4",
    "blue": "#3b82f6",
    "purple": "#a855f7",
    "pink": "#ec4899",
    "white": "#f8fafc",
    "silver": "#94a3b8",
    "black": "#1e293b",
    "brown": "#b45309",
}

# Canonical HSV bin centers (Hue 0..7, Sat 0..3, Val 0..1) for 64-bin histogram queries
COLOR_TARGET_BINS: dict[str, list[tuple[int, int, int]]] = {
    "red": [(0, 2, 1), (0, 3, 1), (7, 2, 1), (7, 3, 1)],
    "orange": [(0, 2, 1), (1, 2, 1), (1, 3, 1)],
    "yellow": [(1, 2, 1), (1, 3, 1), (2, 2, 1)],
    "green": [(2, 2, 1), (2, 3, 1), (3, 2, 1), (3, 3, 1)],
    "cyan": [(3, 2, 1), (3, 3, 1), (4, 2, 1), (4, 3, 1)],
    "blue": [(4, 2, 1), (4, 3, 1), (5, 2, 1), (5, 3, 1)],
    "purple": [(5, 2, 1), (5, 3, 1), (6, 2, 1)],
    "pink": [(6, 2, 1), (6, 3, 1), (7, 2, 1)],
    "white": [(h, 0, 1) for h in range(8)],
    "silver": [(h, 0, 1) for h in range(8)] + [(h, 0, 0) for h in range(8)],
    "black": [(h, 0, 0) for h in range(8)] + [(h, 1, 0) for h in range(8)],
    "brown": [(0, 2, 0), (1, 2, 0), (0, 1, 0), (1, 1, 0)],
}

COLOR_SYNONYMS: dict[str, str] = {
    "red": "red",
    "crimson": "red",
    "scarlet": "red",
    "ruby": "red",
    "maroon": "red",
    "burgundy": "red",
    "orange": "orange",
    "amber": "orange",
    "coral": "orange",
    "tangerine": "orange",
    "yellow": "yellow",
    "gold": "yellow",
    "golden": "yellow",
    "mustard": "yellow",
    "lemon": "yellow",
    "green": "green",
    "emerald": "green",
    "lime": "green",
    "olive": "green",
    "mint": "green",
    "cyan": "cyan",
    "aqua": "cyan",
    "turquoise": "cyan",
    "teal": "cyan",
    "blue": "blue",
    "navy": "blue",
    "cobalt": "blue",
    "azure": "blue",
    "sapphire": "blue",
    "purple": "purple",
    "violet": "purple",
    "lavender": "purple",
    "plum": "purple",
    "indigo": "purple",
    "pink": "pink",
    "magenta": "pink",
    "rose": "pink",
    "fuchsia": "pink",
    "white": "white",
    "ivory": "white",
    "pearl": "white",
    "snowy": "white",
    "silver": "silver",
    "gray": "silver",
    "grey": "silver",
    "metallic": "silver",
    "chrome": "silver",
    "slate": "silver",
    "black": "black",
    "dark": "black",
    "charcoal": "black",
    "obsidian": "black",
    "ebony": "black",
    "brown": "brown",
    "tan": "brown",
    "beige": "brown",
    "bronze": "brown",
    "coffee": "brown",
    "chocolate": "brown",
}

# Canonical Scene & Concept Ontology (mapped to vector dims 256..319)
SCENE_ONTOLOGY: dict[str, tuple[int, set[str]]] = {
    "pool": (
        0,
        {"pool", "pools", "swimming", "swim", "poolside", "jacuzzi", "dive", "diving", "chlorine", "float"},
    ),
    "beach": (
        1,
        {
            "beach",
            "beaches",
            "coast",
            "coastal",
            "seashore",
            "shore",
            "sand",
            "sandy",
            "ocean",
            "sea",
            "waves",
            "surf",
            "tropical",
            "island",
            "palm",
        },
    ),
    "car": (
        2,
        {
            "car",
            "cars",
            "vehicle",
            "vehicles",
            "automobile",
            "sedan",
            "suv",
            "coupe",
            "convertible",
            "truck",
            "hatchback",
            "supercar",
            "roadster",
            "porsche",
            "ferrari",
            "tesla",
            "bmw",
            "audi",
            "mercedes",
            "mustang",
            "corvette",
            "honda",
            "toyota",
        },
    ),
    "recipe": (
        3,
        {
            "recipe",
            "recipes",
            "ingredient",
            "ingredients",
            "cook",
            "cooking",
            "bake",
            "baking",
            "pasta",
            "sauce",
            "garlic",
            "chicken",
            "beef",
            "soup",
            "salad",
            "cake",
            "bread",
            "oven",
            "skillet",
            "simmer",
            "boil",
            "tablespoon",
            "teaspoon",
            "tbsp",
            "tsp",
            "servings",
            "prep",
            "linguine",
            "spaghetti",
            "lasagna",
            "pizza",
        },
    ),
    "food": (
        4,
        {
            "food",
            "meal",
            "dinner",
            "lunch",
            "breakfast",
            "dish",
            "cuisine",
            "restaurant",
            "dessert",
            "fruit",
            "vegetable",
            "cheese",
            "olive",
            "lemon",
            "herb",
            "roast",
            "grill",
        },
    ),
    "document": (
        5,
        {
            "document",
            "documents",
            "manual",
            "guide",
            "documentation",
            "pdf",
            "report",
            "specification",
            "architecture",
            "notes",
            "readme",
            "wiki",
            "handbook",
        },
    ),
    "receipt": (
        6,
        {
            "receipt",
            "receipts",
            "invoice",
            "invoices",
            "bill",
            "statement",
            "tax",
            "payment",
            "total",
            "subtotal",
            "warranty",
            "order",
        },
    ),
    "person": (
        7,
        {"person", "people", "portrait", "selfie", "family", "friends", "kid", "kids", "child", "wedding", "party"},
    ),
    "pet": (
        8,
        {"pet", "pets", "dog", "dogs", "puppy", "cat", "cats", "kitten", "animal", "bird", "horse"},
    ),
    "outdoor": (
        9,
        {
            "outdoor",
            "outdoors",
            "nature",
            "forest",
            "tree",
            "trees",
            "woods",
            "mountain",
            "mountains",
            "hiking",
            "trail",
            "lake",
            "river",
            "park",
            "garden",
            "landscape",
            "sky",
        },
    ),
    "sunset": (
        10,
        {"sunset", "sunrise", "dusk", "dawn", "twilight", "horizon", "evening"},
    ),
    "snow": (
        11,
        {"snow", "winter", "ice", "ski", "skiing", "glacier", "frost", "blizzard"},
    ),
    "indoor": (
        12,
        {"indoor", "indoors", "room", "kitchen", "bedroom", "office", "living", "desk", "home", "house"},
    ),
    "code": (
        13,
        {"code", "script", "function", "class", "python", "javascript", "docker", "compose", "yaml", "config", "api"},
    ),
    "network": (
        14,
        {
            "network",
            "vlan",
            "wireguard",
            "vpn",
            "firewall",
            "router",
            "dns",
            "subnet",
            "ip",
            "ethernet",
            "samba",
            "smb",
        },
    ),
    "storage": (
        15,
        {"storage", "disk", "drive", "raid", "zfs", "btrfs", "unraid", "nvme", "ssd", "hdd", "smart", "backup", "pool"},
    ),
}

EXCLUDED_DIRS: set[str] = {
    ".git",
    ".svn",
    ".hg",
    ".RecycleBin",
    ".Trash",
    "@Recycle",
    "@eaDir",
    ".AppleDouble",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".Spotlight-V100",
    ".fseventsd",
}

EXCLUDED_FILENAMES: set[str] = {
    ".env",
    ".ds_store",
    "secret.key",
    "security.json",
    "sessions.json",
    "api_tokens.json",
    "users.db",
    "users.db-wal",
    "users.db-shm",
    "rag_index.db",
    "rag_index.db-wal",
    "rag_index.db-shm",
    "history.db",
    "rclone.conf",
    "smbpasswd",
    "shadow",
    "id_rsa",
    "id_ed25519",
}

EXCLUDED_EXTENSIONS: set[str] = {
    ".pem",
    ".key",
    ".pfx",
    ".p12",
    ".kdbx",
    ".ovpn",
    ".pyc",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".bin",
    ".iso",
    ".img",
    ".qcow2",
    ".vmdk",
}

DOCUMENT_EXTENSIONS: set[str] = {
    ".md",
    ".txt",
    ".rst",
    ".pdf",
    ".docx",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".conf",
    ".html",
    ".htm",
    ".log",
    ".nfo",
    ".srt",
    ".vtt",
    ".sub",
}

CODE_EXTENSIONS: set[str] = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".sh",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".css",
    ".sql",
}

IMAGE_EXTENSIONS: set[str] = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".gif",
    ".tiff",
    ".tif",
    ".heic",
}

AUDIO_EXTENSIONS: set[str] = {
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
}

VIDEO_EXTENSIONS: set[str] = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".ts",
    ".m2ts",
    ".mpg",
    ".mpeg",
}

_FTS5_RESERVED = {"and", "or", "not", "near"}
_STOPWORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "what",
    "whats",
    "where",
    "wheres",
    "when",
    "whens",
    "who",
    "whos",
    "how",
    "hows",
    "why",
    "whys",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "about",
    "me",
    "my",
    "find",
    "show",
    "search",
    "get",
    "tell",
    "photos",
    "photo",
    "picture",
    "pictures",
    "image",
    "images",
    "file",
    "files",
    "color",
    "coloured",
    "colored",
    "specific",
    "some",
    "any",
    "can",
    "you",
    "please",
}


# Unicode tokenisation (AI-13). Chinese, Japanese and Korean have no spaces between words,
# so a run of those characters becomes overlapping character pairs ("红烧肉" -> "红烧", "烧肉").
# Latin, accented and Cyrillic words are kept whole, as before.
_CJK_CHARS = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af"
_CJK_RUN_RE = re.compile(rf"[{_CJK_CHARS}]")
_TOKEN_RE = re.compile(rf"[{_CJK_CHARS}]+|[a-z0-9_\u00c0-\u024f\u0400-\u04ff]+")


_SUB_TIMING = re.compile(r"\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}[^\n\]]*")
_SUB_INDEX = re.compile(r"^\s*\d+\s*$", re.M)
_MICRODVD = re.compile(r"\{\d+\}\{\d*\}")
SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".sub"}


def text_for_embedding(file_ext: str, text: str) -> str:
    """The text a model embeds. Subtitles lose cue numbers and timings: the tokenizer spends a
    token per digit, so they were two thirds of a subtitle's tokens and carry no meaning."""
    if (file_ext or "").lower() not in SUBTITLE_EXTENSIONS:
        return text
    t = _SUB_TIMING.sub(" ", text)
    t = _MICRODVD.sub(" ", t)
    t = _SUB_INDEX.sub("", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def binary_ratio(text: str, sample: int = 20000) -> float:
    """Share of characters that never occur in real text: control characters (other than tab and
    line breaks), C1 controls, U+FFFD and private-use or unassigned code points. Binary data read
    as Latin-1 scores about 0.25; real text in any language scores near 0."""
    t = text[:sample]
    if not t:
        return 0.0
    bad = 0
    for ch in t:
        o = ord(ch)
        if o < 32:
            bad += ch not in "\t\n\r"
        elif 0x7F <= o <= 0x9F or o == 0xFFFD or 0xE000 <= o <= 0xF8FF or o >= 0xF0000:
            bad += 1
    return bad / len(t)


def looks_like_binary(text: str, threshold: float = 0.05) -> bool:
    """True for text that is really binary data (compressed PDF streams, VobSub .sub files, ...)."""
    return binary_ratio(text) > threshold


def text_tokens(lowered: str) -> list[str]:
    """Words of already lower-cased text, with CJK runs split into character bigrams."""
    out: list[str] = []
    for tok in _TOKEN_RE.findall(lowered or ""):
        if _CJK_RUN_RE.match(tok):
            out.extend([tok[i : i + 2] for i in range(len(tok) - 1)] or [tok])
        else:
            out.append(tok)
    return out


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RUN_RE.search(text or ""))


def build_safe_fts5_query(raw_query: str, remove_stopwords: bool = True) -> str:
    """
    Converts arbitrary user input into a 100% syntax-error-free SQLite FTS5 MATCH query.
    Neutralizes quotes, hyphens, colons, parens, and FTS5 reserved keywords.
    """
    if not raw_query or not isinstance(raw_query, str):
        return ""

    cleaned = re.sub(r"(\w)['’]s\b", r"\1s", raw_query.lower())
    raw_tokens = re.findall(r"[a-z0-9_\u00c0-\u024f\u0400-\u04ff\u4e00-\u9fff]+", cleaned)
    if not raw_tokens:
        return ""

    filtered = [t for t in raw_tokens if t not in _FTS5_RESERVED and len(t) <= 64]
    if remove_stopwords:
        meaningful = [t for t in filtered if t not in _STOPWORDS and (len(t) >= 2 or t.isdigit() or ord(t[0]) > 127)]
        if meaningful:
            filtered = meaningful

    if not filtered:
        return ""

    seen: set[str] = set()
    unique_tokens: list[str] = []
    for t in filtered:
        if t not in seen:
            seen.add(t)
            unique_tokens.append(t)
        if len(unique_tokens) >= 16:
            break

    fts_parts: list[str] = []
    for tok in unique_tokens:
        safe_tok = tok.replace('"', '""')
        if len(safe_tok) >= 5 and safe_tok.isascii():
            fts_parts.append(f'"{safe_tok}"*')
        elif len(safe_tok) >= 3 and safe_tok.isascii() and not safe_tok.endswith("s"):
            fts_parts.append(f'"{safe_tok}"')
            fts_parts.append(f'"{safe_tok}s"')
        else:
            fts_parts.append(f'"{safe_tok}"')

    return " OR ".join(fts_parts)


def _token_matches_word(tok: str, text: str) -> bool:
    """
    Checks whole-word (or simple plural/singular) match so short tokens like 'car'
    never false-match substrings inside 'cards', 'removeCards', or 'carlos'.
    """
    if not tok or not text:
        return False
    if _has_cjk(tok):
        return tok in text  # no word boundaries inside a CJK run
    if len(tok) <= 4 and tok.isascii():
        base = tok[:-1] if (len(tok) == 4 and tok.endswith("s")) else tok
        return bool(re.search(rf"\b{re.escape(base)}(?:s|es)?\b", text))
    return bool(re.search(rf"\b{re.escape(tok)}", text))


def _normalize_pdf_broken_words(text: str) -> str:
    """
    Repairs PDF kerning/line-break word splits (e.g. 'Health Car\\ne' -> 'Health Care',
    'car\\nrot' -> 'carrot', 'La id\\nea' -> 'La idea', 'bus\\ncar' -> 'buscar'),
    strips leading [breadcrumb] prefixes and binary PDF Mojibake tokens, and collapses whitespace.
    """
    if not text:
        return ""
    s = str(text).lstrip()
    # Strip leading [breadcrumb > section] prefix added during chunking
    if s.startswith("["):
        end_bracket = s.find("]", 0, 220)
        if end_bracket > 0:
            s = s[end_bracket + 1 :].lstrip()
    s = re.sub(r"^`?\]\s*", "", s)
    # Remove octal escape artifacts (\222, \037, \341) and control characters
    s = re.sub(r"\\[0-7]{3}", " ", s)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", s)
    # Rejoin mid-word line-breaks across 2 passes (e.g. 'id\ne\na' -> 'idea', 'Car\ne' -> 'Care')
    for _ in range(2):
        s = re.sub(r"([A-Za-zÀ-ÿ])-?[ \t]*\n[ \t]*([a-zà-ÿ])", r"\1\2", s)
    collapsed = re.sub(r"\s+", " ", s).strip()
    # Filter out encrypted-font / binary PDF Mojibake tokens
    clean_words: list[str] = []
    for tok in collapsed.split(" "):
        if re.search(r"[®¤µ×÷þÿ¶§ª«¬¯±²³´¸¹º»¼½¾]", tok):
            continue
        if re.search(r"[A-Za-z0-9][@#$%^&*_+=<>|\\~`]+[A-Za-z0-9#]*|[A-Z0-9]{2,}#", tok):
            continue
        if re.search(r"\d", tok) and re.search(r"[^\x00-\x7f]", tok):
            continue
        clean_words.append(tok)
    return " ".join(clean_words).strip()


def parse_multimodal_query(raw_query: str) -> dict[str, Any]:
    """
    Decomposes a natural language query into explainable color filters, scene/object tags,
    modality hints, and semantic search tokens.
    """
    q = str(raw_query or "").strip()
    cleaned = re.sub(r"(\w)['’]s\b", r"\1s", q.lower())
    tokens = re.findall(r"[a-z0-9_\u00c0-\u024f\u0400-\u04ff\u4e00-\u9fff]+", cleaned)

    auto_colors: list[str] = []
    auto_scenes: list[str] = []
    content_tokens: list[str] = []

    for tok in tokens:
        if tok in COLOR_SYNONYMS:
            c = COLOR_SYNONYMS[tok]
            if c not in auto_colors:
                auto_colors.append(c)
        for scene_slug, (_, syn_set) in SCENE_ONTOLOGY.items():
            if tok in syn_set or (tok.endswith("s") and tok[:-1] in syn_set):
                if scene_slug not in auto_scenes:
                    auto_scenes.append(scene_slug)
        if tok not in _STOPWORDS:
            content_tokens.append(tok)

    # Determine modality hint
    photo_words = {"photo", "photos", "picture", "pictures", "image", "images", "img", "pic", "camera", "selfie"}
    doc_words = {"recipe", "recipes", "doc", "docs", "document", "manual", "guide", "pdf", "note", "notes", "invoice"}
    visual_scenes = {"pool", "beach", "car", "person", "pet", "sunset", "snow"}

    modality_hint = "all"
    if any(t in photo_words for t in tokens) or (
        (auto_colors or any(s in visual_scenes for s in auto_scenes)) and not any(t in doc_words for t in tokens)
    ):
        modality_hint = "photos"
    elif "recipe" in auto_scenes or any(t in {"recipe", "recipes", "ingredients", "cook"} for t in tokens):
        modality_hint = "recipes"
    elif any(t in doc_words for t in tokens):
        modality_hint = "documents"

    return {
        "raw_query": q,
        "tokens": content_tokens or tokens,
        "auto_colors": auto_colors,
        "auto_scenes": auto_scenes,
        "semantic_query": " ".join(content_tokens or tokens),
        "modality_hint": modality_hint,
    }


def classify_rgb_pixel(r: int, g: int, b: int) -> str:
    """
    Classifies an RGB pixel (0..255) into one of the 12 canonical perceptual colors
    using combined HSV + CIE lightness/saturation thresholds.
    """
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)
    h_deg = h * 360.0

    # Achromatic checks first
    if v < 0.18:
        return "black"
    if v > 0.82 and s < 0.15:
        return "white"
    if s < 0.16:
        return "silver"

    # Brown / warm dark orange check
    if 10.0 <= h_deg < 42.0 and v < 0.52 and s >= 0.20:
        return "brown"

    # Chromatic hue wheel
    if h_deg >= 345.0 or h_deg < 14.0:
        return "red"
    if 14.0 <= h_deg < 38.0:
        return "orange"
    if 38.0 <= h_deg < 68.0:
        return "yellow"
    if 68.0 <= h_deg < 165.0:
        return "green"
    if 165.0 <= h_deg < 200.0:
        return "cyan"
    if 200.0 <= h_deg < 255.0:
        return "blue"
    if 255.0 <= h_deg < 295.0:
        return "purple"
    return "pink"


def build_target_color_histogram(colors: list[str]) -> list[float]:
    """Builds a 64-bin L1-normalized query HSV histogram for requested color filters."""
    hist = [0.0] * 64
    for c in colors:
        cname = COLOR_SYNONYMS.get(c.lower(), c.lower())
        bins = COLOR_TARGET_BINS.get(cname, [])
        for bh, bs, bv in bins:
            idx = bh * 8 + bs * 2 + bv
            if 0 <= idx < 64:
                hist[idx] += 1.0
    total = sum(hist)
    if total > 0:
        hist = [x / total for x in hist]
    return hist


def bhattacharyya_similarity(h1: list[float], h2_blob: bytes | None) -> float:
    if not h1 or not h2_blob or len(h2_blob) != 256:
        return 0.0
    h2 = struct.unpack("<64f", h2_blob)
    score = 0.0
    for a, b in zip(h1, h2, strict=False):
        if a > 0.0 and b > 0.0:
            score += math.sqrt(a * b)
    return max(0.0, min(1.0, score))
