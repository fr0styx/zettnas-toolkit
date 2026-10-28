"""Auto-tags for documents, and the filters search offers with them (B8: document filters).

Each document gets up to MAX_TAGS tags for the kind of paper it is (a bill, a payslip, a
contract...) and one for the year it is about, from words in its name, title and text in
English, German, French, Spanish and Chinese. No model is involved: the rules are fast, run as
each file is indexed, and can be read and fixed here.

Tags live in the index (doc_tags: file_id, tag; the year as "year:2024"). Files indexed before
this get their tags from the text the index already holds (backfill), so no drive is woken.
Search filters on them (rag_engine_search: every tag asked for must be on the file), and
counts() gives the filter chips their numbers, over the files the person may see.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections import Counter
from collections.abc import Iterable
from typing import Any

MAX_TAGS = 3
MIN_SCORE = 2  # a word in the name or title counts 2, one in the text 1
TEXT_CHARS = 20000

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS doc_tags (file_id INTEGER NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (file_id, tag))",
    "CREATE INDEX IF NOT EXISTS idx_doc_tags_tag ON doc_tags(tag, file_id)",
    # every file that was tagged, even with no tag, so the backfill reads each file once
    "CREATE TABLE IF NOT EXISTS doc_tags_done (file_id INTEGER PRIMARY KEY)",
)

# tag -> words that mark it (lower case; Latin ones match whole words, Chinese ones anywhere)
RULES: dict[str, tuple[str, ...]] = {
    "bill": (
        "invoice",
        "receipt",
        "amount due",
        "subtotal",
        "total paid",
        "bill",
        "vat",
        "rechnung",
        "quittung",
        "beleg",
        "rechnungsbetrag",
        "mwst",
        "zahlbar bis",
        "facture",
        "reçu",
        "montant dû",
        "ticket de caisse",
        "tva",
        "factura",
        "recibo",
        "importe total",
        "iva",
        "发票",
        "收据",
        "账单",
        "金额",
    ),
    "bank": (
        "bank statement",
        "account statement",
        "iban",
        "balance",
        "transaction",
        "overdraft",
        "kontoauszug",
        "kontostand",
        "überweisung",
        "girokonto",
        "relevé de compte",
        "solde",
        "virement",
        "extracto",
        "saldo",
        "transferencia",
        "cuenta corriente",
        "银行",
        "对账单",
        "余额",
        "转账",
    ),
    "payslip": (
        "payslip",
        "pay slip",
        "gross pay",
        "net pay",
        "salary",
        "payroll",
        "gehaltsabrechnung",
        "lohnabrechnung",
        "bruttolohn",
        "nettolohn",
        "gehalt",
        "bulletin de salaire",
        "fiche de paie",
        "salaire brut",
        "salaire net",
        "nómina",
        "salario bruto",
        "salario neto",
        "工资单",
        "工资",
        "薪资",
    ),
    "contract": (
        "contract",
        "agreement",
        "terms and conditions",
        "hereby",
        "notice period",
        "vertrag",
        "vereinbarung",
        "kündigungsfrist",
        "unterschrift",
        "contrat",
        "préavis",
        "signature",
        "contrato",
        "acuerdo",
        "firma",
        "preaviso",
        "合同",
        "协议",
        "签署",
    ),
    "insurance": (
        "insurance",
        "policy number",
        "premium",
        "insured",
        "claim",
        "coverage",
        "versicherung",
        "versicherungsnummer",
        "beitrag",
        "schadensfall",
        "assurance",
        "numéro de police",
        "cotisation",
        "sinistre",
        "seguro",
        "póliza",
        "prima",
        "siniestro",
        "保险",
        "保单",
        "理赔",
    ),
    "tax": (
        "tax return",
        "tax",
        "irs",
        "hmrc",
        "tax year",
        "deductible",
        "steuer",
        "steuererklärung",
        "finanzamt",
        "steuerbescheid",
        "impôt",
        "impots",
        "déclaration de revenus",
        "avis d'imposition",
        "impuesto",
        "declaración de la renta",
        "hacienda",
        "税",
        "纳税",
        "报税",
    ),
    "medical": (
        "doctor",
        "prescription",
        "diagnosis",
        "vaccination",
        "hospital",
        "patient",
        "arzt",
        "rezept",
        "diagnose",
        "impfung",
        "krankenhaus",
        "praxis",
        "médecin",
        "ordonnance",
        "diagnostic",
        "vaccin",
        "hôpital",
        "médico",
        "receta",
        "diagnóstico",
        "vacuna",
        "hospital",
        "医院",
        "医生",
        "处方",
        "疫苗",
        "诊断",
    ),
    "manual": (
        "manual",
        "user guide",
        "instructions",
        "warranty",
        "troubleshooting",
        "safety instructions",
        "bedienungsanleitung",
        "anleitung",
        "garantie",
        "gewährleistung",
        "fehlerbehebung",
        "mode d'emploi",
        "dépannage",
        "manual de usuario",
        "instrucciones",
        "garantía",
        "说明书",
        "保修",
        "使用指南",
        "故障",
    ),
    "school": (
        "school",
        "teacher",
        "homework",
        "report card",
        "pupil",
        "class trip",
        "schule",
        "lehrer",
        "lehrerin",
        "hausaufgabe",
        "zeugnis",
        "elternabend",
        "école",
        "enseignant",
        "devoirs",
        "bulletin scolaire",
        "escuela",
        "colegio",
        "profesor",
        "deberes",
        "boletín de notas",
        "学校",
        "老师",
        "作业",
        "成绩单",
    ),
    "travel": (
        "flight",
        "boarding pass",
        "booking",
        "hotel",
        "itinerary",
        "check-in",
        "passport",
        "flug",
        "bordkarte",
        "buchung",
        "reiseplan",
        "reisepass",
        "carte d'embarquement",
        "réservation",
        "passeport",
        "vuelo",
        "tarjeta de embarque",
        "reserva",
        "pasaporte",
        "航班",
        "登机牌",
        "酒店",
        "机票",
        "护照",
    ),
    "home": (
        "rent",
        "lease",
        "tenancy",
        "landlord",
        "tenant",
        "electricity",
        "meter reading",
        "utility",
        "miete",
        "mietvertrag",
        "vermieter",
        "mieter",
        "strom",
        "nebenkosten",
        "zählerstand",
        "loyer",
        "bail",
        "propriétaire",
        "locataire",
        "électricité",
        "alquiler",
        "arrendamiento",
        "casero",
        "inquilino",
        "luz",
        "房租",
        "租房",
        "房东",
        "电费",
        "水费",
    ),
    "car": (
        "vehicle",
        "registration",
        "mileage",
        "service history",
        "number plate",
        "fahrzeug",
        "kfz",
        "tüv",
        "zulassung",
        "kilometerstand",
        "véhicule",
        "carte grise",
        "contrôle technique",
        "kilométrage",
        "vehículo",
        "itv",
        "matrícula",
        "kilometraje",
        "汽车",
        "车辆",
        "行驶证",
        "保养",
    ),
}
TAGS = tuple(RULES) + ("recipe",)
_CJK = re.compile(r"[一-鿿]")
_CJK_NOT_AFTER = {"账单": "对"}  # 账单 is a bill, 对账单 a bank statement (AI-36)


def _word_pattern(w: str) -> re.Pattern[str]:
    if not _CJK.search(w):
        return re.compile(rf"(?<![\w]){re.escape(w)}(?![\w])")
    before = _CJK_NOT_AFTER.get(w)
    return re.compile((f"(?<!{re.escape(before)})" if before else "") + re.escape(w))


_PATTERNS = {tag: [(w, _word_pattern(w)) for w in words] for tag, words in RULES.items()}
_YEAR = re.compile(r"(?<!\d)(19[89]\d|20\d\d)(?!\d)")

# Words that also mean something everyday (a company in German, light in Spanish, a balance in
# yoga, premium coffee): they count half, so they need company before they tag a file (AI-36)
AMBIGUOUS = frozenset(
    {
        "bill", "vat", "balance", "transaction", "claim", "premium", "coverage", "signature", "firma",
        "registration", "solde", "saldo", "prima", "receta", "rezept", "praxis", "luz", "itv", "iva",
        "tax", "patient", "manual", "instructions", "garantie", "booking", "hotel", "reserva", "school",
        "teacher", "strom", "rent", "gehalt", "beitrag", "salary", "金额", "余额", "税", "保养", "故障",
        "老师", "学校", "酒店", "工资",
    }
)  # fmt: skip

# Words a question uses for a kind of paper ("my bills from 2024", "Rechnungen 2024"): the chat
# filters on that tag (AI-36). Latin words match whole words, Chinese ones anywhere.
QUESTION_WORDS: dict[str, tuple[str, ...]] = {
    "bill": ("bills", "invoices", "receipts", "rechnungen", "quittungen", "belege", "factures", "reçus", "facturas", "recibos", "发票", "账单", "收据"),
    "bank": ("bank statements", "account statements", "kontoauszüge", "relevés", "extractos", "对账单"),
    "payslip": ("payslips", "pay slips", "salary slips", "gehaltsabrechnungen", "lohnabrechnungen", "fiches de paie", "bulletins de salaire", "nóminas", "工资单"),
    "contract": ("contracts", "verträge", "contrats", "contratos", "合同"),
    "insurance": ("insurance", "versicherungen", "versicherung", "assurances", "assurance", "seguros", "保险"),
    "tax": ("taxes", "tax return", "tax returns", "steuern", "steuererklärung", "impôts", "impuestos", "报税"),
    "medical": ("medical", "medical records", "arztbriefe", "befunde", "dossier médical", "historial médico", "病历"),
    "manual": ("manuals", "user guides", "anleitungen", "bedienungsanleitungen", "modes d'emploi", "manuales", "说明书"),
    "school": ("school papers", "report cards", "zeugnisse", "bulletins scolaires", "boletines", "成绩单"),
    "travel": ("travel documents", "boarding passes", "bookings", "reiseunterlagen", "billets", "reservas", "机票"),
    "home": ("rent", "lease", "utility bills", "mietvertrag", "nebenkosten", "loyer", "alquiler", "房租"),
    "car": ("car papers", "vehicle documents", "fahrzeugpapiere", "carte grise", "papeles del coche", "行驶证"),
    "recipe": ("recipes", "rezepte", "recettes", "recetas", "菜谱", "食谱"),
}  # fmt: skip
_QUESTION = {tag: [_word_pattern(w) for w in words] for tag, words in QUESTION_WORDS.items()}


def tags_in_question(question: str) -> list[str]:
    """The tags a question asks for: the kinds of paper it names, and its year when it names a
    kind too ("bills from 2024"). Empty when it names none, so the chat searches as before."""
    q = (question or "").lower()
    kinds = [tag for tag, pats in _QUESTION.items() if any(p.search(q) for p in pats)][:2]
    if not kinds:
        return []
    years = _YEAR.findall(q)
    return kinds + ([f"year:{years[0]}"] if len(set(years)) == 1 else [])


def tags_for(name: str, title: str, doc_type: str, text: str, now: float | None = None) -> list[str]:
    """The tags for one document: up to MAX_TAGS kinds, best first, then its year (year:NNNN)."""
    head = f"{name} {title}".lower().replace("_", " ").replace("-", " ")
    body = (text or "")[:TEXT_CHARS].lower()
    scores: dict[str, float] = {}
    for tag, pats in _PATTERNS.items():
        score = 0.0
        for word, rx in pats:
            weight = 0.5 if word in AMBIGUOUS else 1.0
            if rx.search(head):
                score += 2 * weight
            elif rx.search(body):
                score += weight
        if score >= MIN_SCORE:
            scores[tag] = score
    if doc_type == "recipe":
        scores["recipe"] = 99
    elif doc_type == "invoice":
        scores["bill"] = max(scores.get("bill", 0), MIN_SCORE)
    out = sorted(scores, key=lambda t: (-scores[t], TAGS.index(t)))[:MAX_TAGS]
    year = document_year(f"{head} {body}", now)
    if year:
        out.append(f"year:{year}")
    return out


def document_year(text: str, now: float | None = None) -> int | None:
    """The year a document is about: the one it names most often, not after next year."""
    last = time.gmtime(now or time.time()).tm_year + 1
    years = Counter(int(y) for y in _YEAR.findall(text or "") if int(y) <= last)
    if not years:
        return None
    return years.most_common(1)[0][0]


def ensure_schema(conn: sqlite3.Connection) -> None:
    for sql in SCHEMA:
        conn.execute(sql)


def store(conn: sqlite3.Connection, file_id: int, tags: Iterable[str]) -> None:
    conn.execute("DELETE FROM doc_tags WHERE file_id = ?", (file_id,))
    conn.executemany("INSERT OR IGNORE INTO doc_tags (file_id, tag) VALUES (?, ?)", [(file_id, t) for t in tags])
    conn.execute("INSERT OR IGNORE INTO doc_tags_done (file_id) VALUES (?)", (file_id,))


def valid(tags: Iterable[str] | None) -> list[str]:
    """The filter tags a request may ask for: known kinds and year:NNNN."""
    out = []
    for t in tags or []:
        t = str(t).strip().lower()
        if (t in TAGS or re.fullmatch(r"year:(19[89]\d|20\d\d)", t)) and t not in out:
            out.append(t)
    return out[:6]


def filter_sql(tags: list[str], alias: str = "f") -> tuple[str, list[Any]]:
    """SQL that keeps files carrying every one of these tags."""
    if not tags:
        return "", []
    sql = "".join(f" AND {alias}.file_id IN (SELECT file_id FROM doc_tags WHERE tag = ?)" for _ in tags)
    return sql, list(tags)


def counts(conn: sqlite3.Connection, rbac_sql: str, rbac_params: list[Any]) -> dict[str, int]:
    """How many documents the person may see carry each tag (for the filter chips)."""
    rows = conn.execute(
        f"SELECT t.tag, COUNT(*) FROM doc_tags t JOIN indexed_files f ON f.file_id = t.file_id "
        f"WHERE f.parse_status = 'ok' AND {rbac_sql} GROUP BY t.tag",
        rbac_params,
    ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def backfill(conn: sqlite3.Connection, batch: int = 200) -> int:
    """Tags documents indexed before tags existed, from the text already in the index (no disk
    access). Returns how many it tagged; 0 when none are left."""
    rows = conn.execute(
        "SELECT f.file_id, f.file_name, f.doc_title, f.doc_type FROM indexed_files f "
        # documents, and photos whose text made them a bill or a recipe ('photo' was never a
        # modality: photos are 'image', so every photo was read here, AI-36)
        "WHERE (f.modality IN ('document', 'code') OR f.doc_type IN ('invoice', 'recipe')) AND f.parse_status = 'ok' "
        "AND f.file_id NOT IN (SELECT file_id FROM doc_tags_done) LIMIT ?",
        (batch,),
    ).fetchall()
    for fid, name, title, doc_type in rows:
        text = " ".join(
            r[0] or ""
            for r in conn.execute(
                "SELECT chunk_text FROM document_chunks WHERE file_id = ? AND chunk_level != 'parent' "
                "ORDER BY chunk_index LIMIT 40",
                (fid,),
            )
        )
        store(conn, fid, tags_for(name or "", title or "", doc_type or "", text))
    if not rows:
        # files that left the index leave their tags behind; ids are never reused, so drop them
        conn.execute("DELETE FROM doc_tags WHERE file_id NOT IN (SELECT file_id FROM indexed_files)")
        conn.execute("DELETE FROM doc_tags_done WHERE file_id NOT IN (SELECT file_id FROM indexed_files)")
    return len(rows)
