"""The document set for the AI search eval (AI-16): long, Office and scanned files.

The files are generated, the same bytes every run, so the repository holds no binaries and
every fact a question relies on is written down here. build(root) writes them under root in
the corpus layout (<lang>/<topic>/<file>); queries_documents.json and qa_documents.json ask
about them.

- long: a 48-section house handbook (Markdown), a 12-page works agreement (PDF with a text
  layer) and a 30-article building regulation (Word). The facts asked for sit deep inside.
- office: a spreadsheet (xlsx, two sheets), slides with speaker notes (pptx), an OpenDocument
  spreadsheet and text (ods, odt), an RTF itinerary and an email (eml), one in Chinese.
- scanned: PDFs whose pages are only pictures of text (no text layer) and a photo of a
  receipt. Their text is read by the vision model; SCANNED_TEXT is what each page says, which
  the per-commit run hands to the pipeline in place of the model (the nightly run uses the
  real model).
"""

import io
import os
import random
import zipfile
import zlib
from xml.sax.saxutils import escape

FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)

# ---------------------------------------------------------------------------------------------
# long documents
# ---------------------------------------------------------------------------------------------
HANDBOOK_FACTS = [
    ("Heating", "The boiler is a Vaillant ecoTEC plus 832; its service is due every October."),
    (
        "Water softener",
        "The water softener takes granulated tablet salt; refill it when the level drops below the red line.",
    ),
    ("Fuse box", "The fuse box is in the hall cupboard; circuit 9 feeds the garden sockets."),
    ("Storage room", "The key to the storage room hangs on the hook inside the hall cupboard."),
    ("Smoke alarms", "The smoke alarms take one 9-volt battery each, changed every January."),
    ("Bins", "General waste goes out on Tuesday night, recycling every second Thursday."),
    ("Garden tap", "The outside tap is turned off at the stopcock under the kitchen sink before the first frost."),
    ("Internet", "The fibre box is behind the TV; the router's admin page is at 192.168.1.1."),
    ("Windows", "The window restrictor key is taped inside the bathroom cabinet door."),
    ("Gutters", "The gutters are cleared every November by Clearflow, phone 01632 960 118."),
    ("Loft", "The loft ladder pole lives on top of the wardrobe in the spare room."),
    ("Doorbell", "The doorbell chime runs on two AA batteries."),
]
FILLER_EN = [
    "Check this part of the house once a season and write down anything unusual.",
    "If something looks wrong, take a photo before you touch it.",
    "The previous owners left the original manuals in the blue folder.",
    "Most small jobs here need only a screwdriver and some patience.",
    "Ask before calling a tradesperson; some repairs are covered by the warranty.",
    "Keep the area clear so it is easy to reach in an emergency.",
    "Write the date on the label when you replace anything.",
]


def handbook() -> str:
    rnd = random.Random(16)
    topics = [
        "Front door",
        "Kitchen",
        "Dishwasher",
        "Oven",
        "Fridge",
        "Washing machine",
        "Dryer",
        "Living room",
        "Fireplace",
        "Stairs",
        "Bathroom",
        "Shower",
        "Toilet",
        "Bedroom",
        "Wardrobes",
        "Spare room",
        "Study",
        "Attic",
        "Cellar",
        "Garage",
        "Driveway",
        "Garden",
        "Shed",
        "Fence",
        "Roof",
        "Chimney",
        "Paint colours",
        "Floors",
        "Lighting",
        "Curtains",
        "Alarm",
        "Post",
        "Parking",
        "Neighbours",
        "Plumbing",
    ]
    # eight sections without a fact come first, so every fact asked about is deep in the file
    rnd.shuffle(topics)
    rest = [(t, None) for t in topics[8:]] + list(HANDBOOK_FACTS)
    rnd.shuffle(rest)
    ordered = [(t, None) for t in topics[:8]] + rest
    out = ["# House handbook", "", "Everything about running this house, room by room.", ""]
    for i, (topic, fact) in enumerate(ordered, start=1):
        out.append(f"## {i}. {topic}")
        body = [rnd.choice(FILLER_EN) for _ in range(6)]
        if fact:
            body.insert(rnd.randrange(1, 6), fact)
        out += [" ".join(body), ""]
    return "\n".join(out)


AGREEMENT_FACTS = {
    23: "§ 23 Rufbereitschaft: Für jedes Wochenende in Rufbereitschaft wird eine Pauschale von 45 Euro gezahlt.",
    31: "§ 31 Homeoffice: Bis zu drei Tage pro Woche dürfen im Homeoffice gearbeitet werden.",
    8: "§ 8 Gleitzeit: Die Kernarbeitszeit liegt zwischen 10 und 15 Uhr.",
}
FILLER_DE = [
    "Die Regelung gilt für alle Beschäftigten des Betriebs.",
    "Änderungen bedürfen der Schriftform und der Zustimmung des Betriebsrats.",
    "Einzelheiten regelt die jeweilige Abteilung im Rahmen dieser Vereinbarung.",
    "Die Vereinbarung wird jährlich überprüft.",
    "Abweichungen sind mit der Personalabteilung abzustimmen.",
]


def agreement_pages() -> list[list[str]]:
    rnd = random.Random(23)
    pages, page = [], []
    for n in range(1, 37):
        lines = [AGREEMENT_FACTS.get(n) or f"§ {n} Allgemeine Bestimmungen {n}."]
        lines += [rnd.choice(FILLER_DE) for _ in range(4)]
        page += lines
        if n % 3 == 0:
            pages.append(page)
            page = []
    return pages


REGULATION_FACTS = {
    27: "Article 27 : les poubelles sont sorties le mardi soir et rentrées le mercredi avant midi.",
    12: "Article 12 : les vélos se rangent uniquement dans le local au sous-sol, porte B.",
    19: "Article 19 : les travaux bruyants sont autorisés en semaine de 9 h à 18 h.",
}
FILLER_FR = [
    "Chaque copropriétaire veille au respect du présent règlement.",
    "Le syndic peut être contacté pour toute question.",
    "Les parties communes doivent rester dégagées.",
    "Toute modification est votée en assemblée générale.",
]


def regulation_paragraphs() -> list[str]:
    rnd = random.Random(27)
    out = ["Règlement de copropriété"]
    for n in range(1, 31):
        out.append(REGULATION_FACTS.get(n) or f"Article {n} : dispositions générales.")
        out += [rnd.choice(FILLER_FR) for _ in range(3)]
    return out


# ---------------------------------------------------------------------------------------------
# writers (minimal, valid files; only the standard library)
# ---------------------------------------------------------------------------------------------
def _zip(path: str, parts: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
            zf.writestr(info, data if isinstance(data, bytes) else data.encode("utf-8"))


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def write_docx(path: str, paragraphs: list[str]) -> None:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{escape(p)}</w:t></w:r></w:p>' for p in paragraphs)
    _zip(
        path,
        {
            "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
            "word/document.xml": f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{body}</w:body></w:document>',
        },
    )


def write_xlsx(path: str, sheets: dict[str, list[list[str | float]]]) -> None:
    strings: list[str] = []

    def sidx(s: str) -> int:
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    parts = {}
    for i, (_name, rows) in enumerate(sheets.items(), start=1):
        xml_rows = []
        for r, row in enumerate(rows, start=1):
            cells = []
            for c, v in enumerate(row):
                ref = f"{chr(65 + c)}{r}"
                if isinstance(v, (int, float)):
                    cells.append(f'<c r="{ref}"><v>{v}</v></c>')
                else:
                    cells.append(f'<c r="{ref}" t="s"><v>{sidx(str(v))}</v></c>')
            xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
        parts[f"xl/worksheets/sheet{i}.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(xml_rows)}</sheetData></worksheet>"
        )
    sheet_list = "".join(
        f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(sheets, start=1)
    )
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    sst = "".join(f"<si><t>{escape(s)}</t></si>" for s in strings)
    _zip(
        path,
        {
            "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            + overrides
            + "</Types>",
            "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
            "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{sheet_list}</sheets></workbook>",
            "xl/_rels/workbook.xml.rels": f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>',
            "xl/sharedStrings.xml": f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{sst}</sst>',
            **parts,
        },
    )


A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'


def _ptext(lines: list[str]) -> str:
    paras = "".join(f"<a:p><a:r><a:t>{escape(t)}</a:t></a:r></a:p>" for t in lines)
    return f"<p:sp><p:txBody>{paras}</p:txBody></p:sp>"


def write_pptx(path: str, slides: list[tuple[list[str], list[str]]]) -> None:
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
    }
    for i, (text, notes) in enumerate(slides, start=1):
        parts[f"ppt/slides/slide{i}.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8"?><p:sld {A}><p:cSld><p:spTree>{_ptext(text)}</p:spTree></p:cSld></p:sld>'
        )
        if notes:
            parts[f"ppt/notesSlides/notesSlide{i}.xml"] = (
                f'<?xml version="1.0" encoding="UTF-8"?><p:notes {A}><p:cSld><p:spTree>{_ptext(notes)}</p:spTree></p:cSld></p:notes>'
            )
    _zip(path, parts)


ODF = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
)


def write_odf(path: str, mimetype: str, body: str) -> None:
    _zip(
        path,
        {
            "mimetype": mimetype,
            "META-INF/manifest.xml": '<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"><manifest:file-entry manifest:full-path="/" manifest:media-type="'
            + mimetype
            + '"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>',
            "content.xml": f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ODF}><office:body>{body}</office:body></office:document-content>',
        },
    )


def write_odt(path: str, paragraphs: list[str]) -> None:
    body = "".join(f"<text:p>{escape(p)}</text:p>" for p in paragraphs)
    write_odf(path, "application/vnd.oasis.opendocument.text", f"<office:text>{body}</office:text>")


def write_ods(path: str, rows: list[list[str]]) -> None:
    trs = "".join(
        "<table:table-row>"
        + "".join(f"<table:table-cell><text:p>{escape(str(c))}</text:p></table:table-cell>" for c in row)
        + "</table:table-row>"
        for row in rows
    )
    write_odf(
        path,
        "application/vnd.oasis.opendocument.spreadsheet",
        f'<office:spreadsheet><table:table table:name="Inventario">{trs}</table:table></office:spreadsheet>',
    )


def _pdf(objects: list[bytes]) -> bytes:
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def _pdf_str(s: str) -> str:
    # WinAnsi covers the German and French letters used here
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_text_pdf(path: str, pages: list[list[str]]) -> None:
    """A PDF with a text layer: Helvetica, one line per string, compressed content streams."""
    n = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    font = 3 + 2 * n
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode()]
    for i, lines in enumerate(pages):
        ops = ["BT /F1 11 Tf 56 790 Td 14 TL"] + [f"({_pdf_str(t)}) Tj T*" for t in lines] + ["ET"]
        data = zlib.compress("\n".join(ops).encode("cp1252"))
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font} 0 R >> >> /Contents {4 + 2 * i} 0 R >>".encode()
        )
        objs.append(f"<< /Length {len(data)} /Filter /FlateDecode >>\nstream\n".encode() + data + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    with open(path, "wb") as f:
        f.write(_pdf(objs))


def _page_image(lines: list[str]):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1240, 1754), (250, 249, 245))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=34)
    y = 120
    for line in lines:
        draw.text((100, y), line, fill=(25, 25, 30), font=font)
        y += 58
    # a little paper texture, the same every run, so the page is a photo-like JPEG, not a flat one
    rnd = random.Random(len(lines))
    for _ in range(4000):
        x, yy = rnd.randrange(1240), rnd.randrange(1754)
        draw.point((x, yy), fill=(200, 198, 190))
    return img


def write_scanned_pdf(path: str, pages: list[list[str]]) -> None:
    """A PDF whose pages are only JPEG pictures of text (what a scanner makes)."""
    n = len(pages)
    kids = " ".join(f"{3 + 3 * i} 0 R" for i in range(n))
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode()]
    for i, lines in enumerate(pages):
        buf = io.BytesIO()
        _page_image(lines).save(buf, "JPEG", quality=82)
        jpg = buf.getvalue()
        img_obj, content_obj = 4 + 3 * i, 5 + 3 * i
        draw = b"q 595 0 0 842 0 0 cm /Im0 Do Q"
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /XObject << /Im0 {img_obj} 0 R >> >> /Contents {content_obj} 0 R >>".encode()
        )
        objs.append(
            f"<< /Type /XObject /Subtype /Image /Width 1240 /Height 1754 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpg)} >>\nstream\n".encode()
            + jpg
            + b"\nendstream"
        )
        objs.append(f"<< /Length {len(draw)} >>\nstream\n".encode() + draw + b"\nendstream")
    with open(path, "wb") as f:
        f.write(_pdf(objs))


def write_photo(path: str, lines: list[str]) -> None:
    img = _page_image(lines).resize((900, 1273))
    img.save(path, "JPEG", quality=85)


# ---------------------------------------------------------------------------------------------
# the set
# ---------------------------------------------------------------------------------------------
SCANNED_TEXT = {
    "en/finance/boiler-repair-invoice-scan.pdf": [
        [
            "HEATWISE PLUMBING LTD",
            "Invoice 2026-0417",
            "Date: 17 April 2026",
            "Boiler service and replacement pressure relief valve",
            "Parts 212.00  Labour 274.00",
            "VAT 97.20",
            "Total due: GBP 583.20",
            "Payment within 14 days",
        ]
    ],
    "de/gesundheit/impfpass-scan.pdf": [
        ["Internationale Bescheinigungen über Impfungen", "Name: Lena Hoffmann"],
        [
            "Tetanus / Diphtherie Auffrischung",
            "Datum: 03.05.2024",
            "Nächste Auffrischung: 2034",
            "Praxis Dr. Albers, Freiburg",
        ],
    ],
    "es/casa/garantia-lavadora-scan.pdf": [
        [
            "CERTIFICADO DE GARANTIA",
            "Lavadora Bosch Serie 6",
            "Numero de serie: WM-55821",
            "Fecha de compra: 02/12/2025",
            "Garantia valida hasta: 12/2028",
            "Servicio tecnico: 900 100 200",
        ]
    ],
    "en/home/hardware-store-receipt.jpg": [
        [
            "OAKFIELD HARDWARE",
            "Water softener salt tablets 25kg  x2   13.98",
            "Brass hose connector        4.50",
            "TOTAL                      18.48",
            "Paid by card  12/03/2026",
        ]
    ],
}

LONG = ["en/home/house-handbook.md", "de/arbeit/betriebsvereinbarung.pdf", "fr/maison/reglement-copropriete.docx"]
OFFICE = [
    "en/finance/household-budget-2026.xlsx",
    "de/homelab/netzplan.pptx",
    "es/casa/inventario-trastero.ods",
    "en/work/offsite-meeting-notes.odt",
    "en/travel/leeds-itinerary.rtf",
    "fr/finances/releve-prelevement.eml",
    "zh/工作/年度计划.xlsx",
]
SCANNED = list(SCANNED_TEXT)


def build(root: str) -> list[str]:
    """Writes the set under root; returns the relative paths written."""

    def p(rel):
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        return full

    with open(p(LONG[0]), "w", encoding="utf-8") as f:
        f.write(handbook())
    write_text_pdf(p(LONG[1]), agreement_pages())
    write_docx(p(LONG[2]), regulation_paragraphs())

    write_xlsx(
        p(OFFICE[0]),
        {
            "Budget": [
                ["Category", "Planned per year (GBP)"],
                ["Heating maintenance", 650],
                ["Electricity", 1100],
                ["Car insurance", 912.40],
                ["Internet", 479.88],
                ["Window cleaning", 180],
                ["Gutters", 95],
            ],
            "Actuals": [
                ["Month", "Category", "Spent"],
                ["January", "Electricity", 104.10],
                ["February", "Internet", 39.99],
            ],
        },
    )
    write_pptx(
        p(OFFICE[1]),
        [
            (["Heimnetz 2026", "Überblick über VLANs und Geräte"], []),
            (
                ["VLAN-Plan", "VLAN 10: Familie", "VLAN 30: Kameras", "VLAN 40: Gäste-WLAN"],
                ["Die Kameras hängen am Switch im Keller, Port 12."],
            ),
            (["Backup", "Nachts um 2 Uhr auf das NAS"], []),
        ],
    )
    write_ods(
        p(OFFICE[2]),
        [
            ["Caja", "Contenido"],
            ["Caja 3", "Ropa de invierno"],
            ["Caja 7", "Adornos de Navidad"],
            ["Caja 9", "Herramientas del jardín"],
        ],
    )
    write_odt(
        p(OFFICE[3]),
        [
            "Offsite planning meeting, 3 March 2026",
            "Attendees: Priya, Tom, Jonas",
            "Decision: the team offsite moves to 14 May 2026 in Leeds.",
            "Budget per person: 220 pounds.",
        ],
    )
    with open(p(OFFICE[4]), "w", encoding="utf-8") as f:
        f.write(
            "{\\rtf1\\ansi{\\fonttbl{\\f0 Arial;}}\\f0 Itinerary for Leeds\\par "
            "13 May 2026: train from Manchester Piccadilly at 18:40\\par "
            "14 May 2026: offsite starts at 09:30 at the Corn Exchange\\par }"
        )
    with open(p(OFFICE[5]), "w", encoding="utf-8") as f:
        f.write(
            "From: service@edf.example\nTo: famille.martin@example.org\nSubject: Votre prélèvement mensuel\n"
            "Content-Type: text/plain; charset=utf-8\n\n"
            "Bonjour, votre prélèvement mensuel EDF de 84,20 EUR sera effectué le 5 de chaque mois.\n"
        )
    write_xlsx(p(OFFICE[6]), {"计划": [["季度", "目标"], ["第三季度", "客户满意度 92%"], ["第四季度", "新开两家门店"]]})

    for rel, pages in SCANNED_TEXT.items():
        if rel.endswith(".pdf"):
            write_scanned_pdf(p(rel), pages)
        else:
            write_photo(p(rel), pages[0])
    return LONG + OFFICE + SCANNED


def page_text_for(jpeg: bytes) -> str:
    """The stand-in for the vision model on a scanned PDF page: what that page says."""
    for rel, pages in SCANNED_TEXT.items():
        if not rel.endswith(".pdf"):
            continue
        for lines in pages:
            buf = io.BytesIO()
            _page_image(lines).save(buf, "JPEG", quality=82)
            if buf.getvalue() == jpeg:
                return "\n".join(lines)
    return ""


def photo_text_for(path: str) -> tuple[str, str]:
    """The stand-in for the vision model on a photo: a caption and the text in it."""
    for rel, pages in SCANNED_TEXT.items():
        if not rel.endswith(".pdf") and path.replace(os.sep, "/").endswith(rel):
            return "a printed shop receipt", "\n".join(pages[0])
    return "", ""
