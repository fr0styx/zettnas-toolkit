"""The household's five languages for search (AI-13): stop words, colours, scenes and kinds of
file in German, French, Spanish and Chinese next to English; what a question asks (a how-to, a
list); and the language most of the household's documents are written in.

These lists are read on the question side and when photos are tagged. The lexical vectors keep
using the English lists in rag_text, so every stored vector stays valid.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections import Counter

# The English stop words the lexical vectors and keyword checks have always used; rag_text
# reads them from here (this module imports nothing of the search, so both can use it)
ENGLISH_STOPWORDS: frozenset[str] = frozenset(
    [
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
    ]
)
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def _has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))


LANGS = ("en", "de", "fr", "es", "zh")
NAMES = {"en": "English", "de": "German", "fr": "French", "es": "Spanish", "zh": "Chinese (simplified)"}

STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset(ENGLISH_STOPWORDS | {"and", "or", "it", "this", "that", "do", "does", "did", "i", "we", "our", "have", "has", "be", "not"}),
    "de": frozenset(
        ["der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "und", "oder", "ist", "sind", "war", "waren", "wie", "was", "wo", "wann", "warum", "wer", "welche", "welcher", "welches", "mit", "von", "vom", "zu", "zum", "zur", "im", "in", "am", "an", "auf", "aus", "für", "bei", "nach", "über", "unter", "mein", "meine", "meinen", "meiner", "unser", "unsere", "ich", "wir", "du", "sie", "es", "er", "nicht", "kein", "keine", "auch", "noch", "nur", "schon", "hat", "haben", "gibt", "zeig", "zeige", "zeigen", "finde", "finden", "such", "suche", "bitte", "alle", "alles", "dieser", "diese", "dieses", "dass", "ob"]
    ),
    "fr": frozenset(
        ["le", "la", "les", "un", "une", "des", "du", "de", "d", "l", "et", "ou", "est", "sont", "était", "comment", "quoi", "où", "quand", "pourquoi", "qui", "quel", "quelle", "quels", "quelles", "avec", "pour", "par", "sur", "dans", "au", "aux", "en", "mon", "ma", "mes", "notre", "nos", "je", "nous", "tu", "vous", "il", "elle", "ils", "elles", "ne", "pas", "plus", "aussi", "déjà", "a", "ont", "y", "montre", "montrer", "trouve", "trouver", "cherche", "chercher", "stp", "svp", "tous", "tout", "toutes", "ce", "cet", "cette", "ces", "que", "qu"]
    ),
    "es": frozenset(
        ["el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "y", "o", "es", "son", "era", "cómo", "como", "qué", "que", "dónde", "donde", "cuándo", "cuando", "por", "porqué", "quién", "cuál", "cuáles", "con", "para", "en", "sobre", "mi", "mis", "nuestro", "nuestra", "yo", "nosotros", "tú", "usted", "él", "ella", "ellos", "no", "ya", "también", "hay", "muestra", "muéstrame", "busca", "buscar", "encuentra", "encontrar", "todos", "todas", "todo", "este", "esta", "estos", "estas", "ese", "esa", "se", "lo"]
    ),
    "zh": frozenset(
        ["的", "了", "是", "在", "我", "我们", "你", "有", "和", "与", "吗", "呢", "吧", "啊", "什么", "哪里", "哪儿", "怎么", "怎样", "如何", "为什么", "请", "给", "把", "被", "这", "那", "这个", "那个", "一个", "都", "也", "就", "还", "要", "找", "找一下", "查", "查找", "显示", "所有", "一下"]
    ),
}  # fmt: skip
ALL_STOPWORDS: frozenset[str] = frozenset().union(*STOPWORDS.values())

# word -> canonical colour (rag_text.CANONICAL_COLORS). Words with another everyday meaning in
# English ("rose", "red" in Spanish is a network) are left out.
COLOR_WORDS: dict[str, str] = {
    **dict.fromkeys(("rot", "rote", "roter", "rotes", "roten", "rouge", "rouges", "rojo", "roja", "rojos", "rojas", "红色", "红"), "red"),
    **dict.fromkeys(("blau", "blaue", "blauer", "blaues", "blauen", "bleu", "bleue", "bleus", "azul", "azules", "蓝色", "蓝"), "blue"),
    **dict.fromkeys(("grün", "grüne", "grüner", "grünes", "grünen", "vert", "verte", "verts", "verde", "verdes", "绿色", "绿"), "green"),
    **dict.fromkeys(("gelb", "gelbe", "gelber", "gelbes", "gelben", "jaune", "jaunes", "amarillo", "amarilla", "黄色"), "yellow"),
    **dict.fromkeys(("orangene", "oranger", "orangefarben", "naranja", "anaranjado", "橙色", "橘色"), "orange"),
    **dict.fromkeys(("lila", "violett", "violette", "violet", "morado", "morada", "violeta", "紫色", "紫"), "purple"),
    **dict.fromkeys(("rosa", "rosé", "pinke", "rosado", "rosada", "粉色", "粉红", "粉红色"), "pink"),
    **dict.fromkeys(("braun", "braune", "brauner", "braunes", "marron", "brun", "brune", "marrón", "café", "棕色", "咖啡色"), "brown"),
    **dict.fromkeys(("schwarz", "schwarze", "schwarzer", "schwarzes", "noir", "noire", "noirs", "negro", "negra", "黑色", "黑"), "black"),
    **dict.fromkeys(("weiß", "weiss", "weiße", "weisse", "weißer", "weißes", "blanc", "blanche", "blanco", "blanca", "白色", "白"), "white"),
    **dict.fromkeys(("grau", "graue", "silber", "silberne", "gris", "grise", "argent", "argenté", "plateado", "plata", "灰色", "银色"), "silver"),
    **dict.fromkeys(("türkis", "turquoise", "turquesa", "cian", "青色"), "cyan"),
}  # fmt: skip

# scene slug (rag_text.SCENE_ONTOLOGY) -> words. Left out: words that mean something else in
# English ("auto", "chat", "see") or another scene ("winter" is a season too).
SCENE_WORDS: dict[str, tuple[str, ...]] = {
    "pool": ("schwimmbad", "freibad", "piscine", "piscina", "游泳池", "泳池"),
    "beach": ("strand", "meer", "küste", "plage", "mer", "playa", "costa", "海滩", "沙滩", "海边"),
    "car": ("wagen", "fahrzeug", "voiture", "coche", "carro", "汽车", "车子"),
    "recipe": ("rezept", "rezepte", "kochen", "backen", "zutaten", "recette", "recettes", "ingrédients", "receta", "recetas", "cocinar", "ingredientes", "食谱", "菜谱", "做法"),
    "food": ("essen", "gericht", "mahlzeit", "nourriture", "repas", "comida", "plato", "美食"),
    "document": ("dokument", "dokumente", "anleitung", "handbuch", "documents", "manuel", "documento", "documentos", "文档", "说明书"),
    "receipt": ("rechnung", "rechnungen", "quittung", "beleg", "facture", "factures", "reçu", "factura", "facturas", "recibo", "发票", "收据"),
    "person": ("familie", "kinder", "leute", "hochzeit", "famille", "enfants", "mariage", "familia", "niños", "boda", "家人", "孩子", "婚礼"),
    "pet": ("hund", "hunde", "katze", "katzen", "haustier", "chien", "chiens", "chiot", "perro", "perros", "gato", "gatos", "mascota", "狗", "猫", "宠物"),
    "outdoor": ("wald", "berg", "berge", "garten", "wandern", "forêt", "montagne", "lac", "jardin", "randonnée", "bosque", "montaña", "lago", "jardín", "senderismo", "森林", "湖边", "花园", "徒步", "爬山"),
    "sunset": ("sonnenuntergang", "sonnenaufgang", "abendrot", "coucher", "atardecer", "amanecer", "日落", "日出", "夕阳"),
    "snow": ("schnee", "neige", "nieve", "雪", "滑雪"),
    "indoor": ("küche", "wohnzimmer", "schlafzimmer", "salon", "chambre", "cocina", "salón", "dormitorio", "厨房", "客厅", "卧室"),
    "code": ("skript", "skripte", "código", "代码", "脚本"),
    "network": ("netzwerk", "réseau", "路由器", "网络"),
    "storage": ("sicherung", "festplatte", "sauvegarde", "disque", "disco", "备份", "硬盘"),
}  # fmt: skip
_SCENE_OF = {w: slug for slug, words in SCENE_WORDS.items() for w in words}
PHOTO_WORDS = frozenset(
    ["foto", "fotos", "bild", "bilder", "aufnahme", "aufnahmen", "imagen", "imágenes", "照片", "相片", "图片"]
)
DOC_WORDS = frozenset(
    [
        "dokument",
        "dokumente",
        "anleitung",
        "handbuch",
        "rezept",
        "rezepte",
        "rechnung",
        "rechnungen",
        "quittung",
        "notizen",
        "documents",
        "manuel",
        "recette",
        "recettes",
        "facture",
        "factures",
        "notes",
        "documento",
        "documentos",
        "receta",
        "recetas",
        "factura",
        "facturas",
        "recibo",
        "recibos",
        "notas",
        "文档",
        "食谱",
        "菜谱",
        "发票",
        "笔记",
        "说明书",
    ]
)
RECIPE_WORDS = frozenset(
    [
        "rezept",
        "rezepte",
        "zutaten",
        "kochen",
        "recette",
        "recettes",
        "ingrédients",
        "receta",
        "recetas",
        "ingredientes",
        "食谱",
        "菜谱",
        "做法",
        "配料",
    ]
)


def stopwords_for(text: str) -> frozenset[str]:
    """English stop words, plus those of the question's language when it is another one: a word
    like "war", "hat" or "son" is only dropped from a German or Spanish question."""
    lang = detect(text)
    return STOPWORDS["en"] if lang == "en" else STOPWORDS["en"] | STOPWORDS[lang]


def _cjk_words(text: str, words) -> list[str]:
    return [w for w in words if _has_cjk(w) and w in text]


def colors_in(tokens: list[str], text: str) -> list[str]:
    """Canonical colours a question names in any of the five languages."""
    out = [COLOR_WORDS[t] for t in tokens if t in COLOR_WORDS]
    out += [COLOR_WORDS[w] for w in _cjk_words(text, COLOR_WORDS) if len(w) > 1]  # 红色, not 红 inside 红烧肉
    return list(dict.fromkeys(out))


def scenes_in(tokens: list[str], text: str) -> list[str]:
    out = [_SCENE_OF[t] for t in tokens if t in _SCENE_OF]
    out += [_SCENE_OF[w] for w in _cjk_words(text, _SCENE_OF)]
    return list(dict.fromkeys(out))


def any_word(tokens: list[str], text: str, words: frozenset[str]) -> bool:
    return any(t in words for t in tokens) or bool(_cjk_words(text, words))


# What a question asks, beyond English (rag_embeddings keeps the English rules)
QA_RE = re.compile(
    r"^(wie|warum|weshalb|wieso|was\s+(ist|sind|bedeutet|mache)|wo\s+(ist|sind|finde|steht)|wann|kann\s+ich|darf\s+ich|"
    r"erkläre?|comment|pourquoi|qu['’]est-ce|où|quand|est-ce\s+que|puis-je|explique|cómo|como\s+(se|puedo|hago)|"
    r"por\s+qué|qué\s+(es|son|significa|hago)|dónde|cuándo|puedo|explica)\b"
    r"|(怎么|如何|为什么|为何|什么是|是什么|在哪|哪里|能不能|可以吗|吗[？?]?$|呢[？?]?$)",
    re.IGNORECASE,
)
CLASS_RE = re.compile(
    r"\b(liste\s+alle|alle\s+\w+\s+auflisten|finde\s+alle|duplikate|lister\s+tou[ts]|liste\s+de\s+tou[ts]|doublons|"
    r"listar\s+tod[oa]s|lista\s+de\s+tod[oa]s|duplicados)\b|(列出|所有的|重复的文件|分类)",
    re.IGNORECASE,
)


def detect(text: str) -> str:
    """The language of a piece of text: Chinese by its characters, the others by stop words."""
    t = (text or "").lower()
    if not t.strip():
        return "en"
    cjk = len(re.findall(r"[一-鿿]", t))
    if cjk >= 8 and cjk * 3 >= len(re.sub(r"\s", "", t)):
        return "zh"
    words = re.findall(r"[a-zà-ÿ']+", t)
    scores = {lang: sum(w in STOPWORDS[lang] for w in words) for lang in ("en", "de", "fr", "es")}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 2 else "en"


_HOUSEHOLD: dict[str, tuple[float, str]] = {}


def household_language(conn: sqlite3.Connection, db_key: str = "", sample: int = 300) -> str:
    """The language most of the indexed documents are written in; English when there are too few
    to tell. Kept an hour."""
    cached = _HOUSEHOLD.get(db_key)
    if cached and time.time() - cached[0] < 3600:
        return cached[1]
    try:
        rows = conn.execute(
            "SELECT chunk_text FROM document_chunks WHERE chunk_level != 'parent' ORDER BY chunk_id DESC LIMIT ?",
            (sample,),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    votes = Counter(detect(r[0] or "") for r in rows if (r[0] or "").strip())
    lang = votes.most_common(1)[0][0] if sum(votes.values()) >= 20 else "en"
    _HOUSEHOLD[db_key] = (time.time(), lang)
    return lang


def caption_language(cfg: dict, conn: sqlite3.Connection | None = None, db_key: str = "") -> str:
    """The language photo captions are written in: the setting, or with "auto" the household's."""
    chosen = str(cfg.get("caption_language") or "auto").lower()
    if chosen in LANGS:
        return chosen
    return household_language(conn, db_key) if conn is not None else "en"
