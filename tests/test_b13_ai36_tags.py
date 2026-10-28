"""B13 (AI-36): document tags checked against a labelled set in five languages, with a precision
and recall gate per tag; words with an everyday meaning need company; the chat filters on the kind
and year a question names; browsing by a tag needs no embedding (AI-37); audio tags (AI-38)."""

import sqlite3
import struct
import time
import wave
from types import SimpleNamespace

import pytest

from backend.services import rag_tags

NOW = time.mktime((2026, 10, 1, 0, 0, 0, 0, 0, -1))

# (file name, text, the kinds a person would file it under)
LABELLED: list[tuple[str, str, set[str]]] = [
    # bills
    ("invoice_2024_031.pdf", "Invoice no. 2024-031. Subtotal 120.00, VAT 22.80, amount due 142.80.", {"bill"}),
    ("Rechnung Handwerker.pdf", "Rechnungsbetrag 480,00 EUR inkl. MwSt. Zahlbar bis 15.03.2024.", {"bill"}),
    ("facture_edf.pdf", "Facture n° 88231. Montant dû : 64,20 €. TVA 20 %.", {"bill"}),
    ("factura_movil.pdf", "Factura 2024/77. Importe total 35,90 €. IVA incluido.", {"bill"}),
    ("发票_2024.pdf", "增值税发票 金额 ¥560.00 开票日期 2024年3月", {"bill"}),
    ("scan_0042.jpg.txt", "Receipt. Total paid 18.40. Thank you for shopping.", {"bill"}),
    # bank
    (
        "statement_march.pdf",
        "Account statement 01.03-31.03. IBAN GB29 NWBK 6016. Opening balance, closing balance, 14 transactions.",
        {"bank"},
    ),
    ("Kontoauszug_03.pdf", "Kontoauszug Girokonto. Kontostand alt / neu. Überweisung an Stadtwerke.", {"bank"}),
    ("releve_mars.pdf", "Relevé de compte. Solde créditeur. Virement reçu de l'employeur.", {"bank"}),
    ("extracto_banco.pdf", "Extracto de cuenta corriente. Saldo anterior. Transferencia recibida.", {"bank"}),
    ("银行对账单.pdf", "银行对账单 余额 转账 2024年", {"bank"}),
    # payslips
    ("payslip_oct.pdf", "Payslip October. Gross pay 4,200.00. Net pay 2,950.10. Payroll number 1182.", {"payslip"}),
    ("Gehaltsabrechnung_10.pdf", "Gehaltsabrechnung Oktober. Bruttolohn 4.200,00. Nettolohn 2.731,55.", {"payslip"}),
    ("fiche_de_paie.pdf", "Bulletin de salaire. Salaire brut 3 100,00. Salaire net 2 410,00.", {"payslip"}),
    ("nomina_octubre.pdf", "Nómina de octubre. Salario bruto 2.400. Salario neto 1.890.", {"payslip"}),
    ("工资单_十月.pdf", "工资单 应发工资 实发工资 薪资明细", {"payslip"}),
    # contracts
    (
        "employment_contract.pdf",
        "This agreement is made between the parties. Notice period three months. Terms and conditions apply.",
        {"contract"},
    ),
    (
        "Arbeitsvertrag.pdf",
        "Vertrag zwischen den Parteien. Kündigungsfrist drei Monate. Unterschrift beider Seiten.",
        {"contract"},
    ),
    ("contrat_travail.pdf", "Contrat de travail. Préavis d'un mois. Signature des deux parties.", {"contract"}),
    (
        "contrato_servicios.pdf",
        "Contrato de prestación de servicios. Acuerdo entre las partes. Preaviso de 30 días.",
        {"contract"},
    ),
    ("劳动合同.pdf", "劳动合同 甲方 乙方 双方签署本协议", {"contract"}),
    # insurance
    (
        "car_insurance_policy.pdf",
        "Insurance schedule. Policy number 55-2231. Annual premium 640.00. Coverage: third party.",
        {"insurance", "car"},
    ),
    (
        "Versicherung_Hausrat.pdf",
        "Hausratversicherung. Versicherungsnummer 77812. Beitrag jährlich. Schadensfall melden.",
        {"insurance"},
    ),
    (
        "assurance_habitation.pdf",
        "Assurance habitation. Numéro de police 4412. Cotisation annuelle. Déclarer un sinistre.",
        {"insurance"},
    ),
    ("poliza_seguro.pdf", "Póliza de seguro del hogar. Prima anual. En caso de siniestro, llame.", {"insurance"}),
    ("保险单.pdf", "保险 保单号 理赔 流程", {"insurance"}),
    # tax
    ("tax_return_2023.pdf", "Tax return for the tax year 2023. Deductible expenses. Submitted to HMRC.", {"tax"}),
    ("Steuererklärung_2023.pdf", "Einkommensteuererklärung 2023 an das Finanzamt. Steuerbescheid folgt.", {"tax"}),
    ("avis_impot.pdf", "Avis d'imposition 2023. Déclaration de revenus. Impôt sur le revenu.", {"tax"}),
    ("renta_2023.pdf", "Declaración de la renta 2023. Agencia Tributaria, Hacienda. Impuesto a pagar.", {"tax"}),
    ("报税_2023.pdf", "个人所得税 纳税 申报 报税 2023", {"tax"}),
    # medical
    (
        "lab_results.pdf",
        "Patient: J. Doe. Diagnosis: iron deficiency. Doctor's prescription attached. Hospital lab.",
        {"medical"},
    ),
    ("Arztbrief.pdf", "Arztbrief der Praxis Dr. Weber. Diagnose: Bronchitis. Rezept für Antibiotika.", {"medical"}),
    ("ordonnance.pdf", "Ordonnance du médecin. Diagnostic : angine. Hôpital Saint-Louis.", {"medical"}),
    (
        "informe_medico.pdf",
        "Informe del médico. Diagnóstico: gripe. Receta: paracetamol. Vacuna antigripal.",
        {"medical"},
    ),
    ("病历.pdf", "医院 门诊 医生 诊断 处方", {"medical"}),
    # manuals
    ("dishwasher_manual.pdf", "User guide. Safety instructions. Troubleshooting. Warranty two years.", {"manual"}),
    ("Bedienungsanleitung_Kaffee.pdf", "Bedienungsanleitung. Fehlerbehebung. Garantie und Gewährleistung.", {"manual"}),
    ("mode_emploi.pdf", "Mode d'emploi du lave-linge. Dépannage. Garantie deux ans.", {"manual"}),
    ("manual_usuario.pdf", "Manual de usuario. Instrucciones de seguridad. Garantía de dos años.", {"manual"}),
    ("说明书.pdf", "使用指南 说明书 保修 故障排除", {"manual"}),
    # school
    ("report_card_2024.pdf", "Report card. Teacher comments. Homework completed. Pupil: Mia.", {"school"}),
    (
        "Zeugnis_Klasse4.pdf",
        "Zeugnis der Grundschule. Klassenlehrerin. Elternabend am Dienstag. Schule am Park.",
        {"school"},
    ),
    ("bulletin_ecole.pdf", "Bulletin scolaire. École primaire. Devoirs. Enseignant : M. Martin.", {"school"}),
    ("boletin_notas.pdf", "Boletín de notas del colegio. Profesor tutor. Deberes de verano.", {"school"}),
    ("成绩单.pdf", "学校 成绩单 老师 评语 作业", {"school"}),
    # travel
    (
        "boarding_pass.pdf",
        "Boarding pass. Flight LH 400. Check-in closes 40 minutes before. Passport required.",
        {"travel"},
    ),
    ("Buchung_Hotel_Rom.pdf", "Buchungsbestätigung. Hotel Roma. Reiseplan. Flug FCO.", {"travel"}),
    ("reservation_vol.pdf", "Réservation confirmée. Carte d'embarquement. Passeport valide.", {"travel"}),
    ("reserva_vuelo.pdf", "Reserva de vuelo. Tarjeta de embarque. Pasaporte en vigor.", {"travel"}),
    ("机票.pdf", "航班 登机牌 机票 护照", {"travel"}),
    # home
    (
        "tenancy_agreement.pdf",
        "Tenancy agreement between landlord and tenant. Monthly rent 1,100. Lease of twelve months.",
        {"home", "contract"},
    ),
    ("Nebenkosten_2024.pdf", "Nebenkostenabrechnung 2024. Vermieter an Mieter. Zählerstand Strom. Miete.", {"home"}),
    ("quittance_loyer.pdf", "Quittance de loyer. Propriétaire et locataire. Bail du 1er mai.", {"home"}),
    (
        "contrato_alquiler.pdf",
        "Contrato de alquiler. Arrendamiento de vivienda. El casero y el inquilino.",
        {"home", "contract"},
    ),
    ("房租.pdf", "房租 房东 租房 水费 电费", {"home"}),
    # car
    ("car_service.pdf", "Vehicle service history. Mileage 82,000. Registration AB12 CDE. Number plate.", {"car"}),
    ("TÜV_Bericht.pdf", "TÜV Hauptuntersuchung. Fahrzeug Kfz. Kilometerstand 120.000. Zulassung.", {"car"}),
    ("controle_technique.pdf", "Contrôle technique. Véhicule. Kilométrage 95 000. Carte grise.", {"car"}),
    ("itv_coche.pdf", "Inspección ITV. Vehículo. Matrícula 1234 ABC. Kilometraje 60.000.", {"car"}),
    ("汽车保养.pdf", "汽车 车辆 保养 行驶证", {"car"}),
    # everyday papers whose words have another meaning: no kind at all
    ("yoga_notes.txt", "Morning yoga: balance poses, breathing, and a premium mat I liked.", set()),
    ("firma_ausflug.txt", "Der Firma-Ausflug geht dieses Jahr an den See. Wer bringt Kuchen?", set()),
    ("luz_poema.txt", "La luz de la tarde entra por la ventana y el saldo del día es bueno.", set()),
    ("cafe_menu.txt", "Premium coffee, a balance of sweet and bitter. Claim your free cookie.", set()),
    ("recette_pain.txt", "Pour le pain : farine, eau, sel. Laisser lever une nuit.", set()),
    ("hotel_california.txt", "Lyrics notes: the song about a hotel, written in the seventies.", set()),
    ("bill_birthday.txt", "Bill's birthday party on Saturday, bring a salad.", set()),
    ("会议记录.txt", "今天讨论了余额宝的新闻和学校附近的新餐厅。", set()),
    ("gehalt_gedanken.txt", "Gedanken zum Wochenende und zum Garten.", set()),
    ("signature_dish.txt", "My signature dish is a slow roasted tomato soup.", set()),
]
GATES = {"precision": 0.9, "recall": 0.8}


def _kinds(name, text):
    return {t for t in rag_tags.tags_for(name, "", "", text, now=NOW) if not t.startswith("year:")}


def test_every_tag_passes_its_precision_and_recall_gate():
    report = {}
    for tag in rag_tags.RULES:
        tp = fp = fn = 0
        for name, text, want in LABELLED:
            got = tag in _kinds(name, text)
            tp += got and tag in want
            fp += got and tag not in want
            fn += (not got) and tag in want
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        report[tag] = (round(precision, 2), round(recall, 2))
    failing = {t: pr for t, pr in report.items() if pr[0] < GATES["precision"] or pr[1] < GATES["recall"]}
    assert not failing, failing


def test_everyday_words_alone_tag_nothing():
    for name, text, want in LABELLED:
        if not want:
            assert _kinds(name, text) == set(), name


def test_an_ambiguous_word_counts_half_but_two_of_them_still_tag():
    assert _kinds("notes.txt", "The balance looks fine.") == set()
    assert "bank" in _kinds("notes.txt", "The balance and each transaction, IBAN DE12 5001.")


@pytest.mark.parametrize(
    ("question", "want"),
    [
        ("show me my bills from 2024", ["bill", "year:2024"]),
        ("Zeig mir meine Rechnungen 2023", ["bill", "year:2023"]),
        ("mes factures de 2022", ["bill", "year:2022"]),
        ("mis nóminas de 2024", ["payslip", "year:2024"]),
        ("2024年的发票", ["bill", "year:2024"]),
        ("where is the warranty for the dishwasher?", []),
        ("what happened in 2024?", []),  # a year alone filters nothing
        ("contracts signed in 2019 or 2020", ["contract"]),  # two years: no year filter
        ("my insurance and tax returns", ["insurance", "tax"]),
    ],
)
def test_the_chat_hears_the_kind_and_year_a_question_names(question, want):
    assert rag_tags.tags_in_question(question) == want


def test_the_backfill_reads_documents_and_photos_of_bills_but_not_other_photos(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute(
        "CREATE TABLE indexed_files (file_id INTEGER PRIMARY KEY, file_name TEXT, doc_title TEXT, doc_type TEXT, "
        "modality TEXT, parse_status TEXT)"
    )
    conn.execute(
        "CREATE TABLE document_chunks (file_id INTEGER, chunk_index INTEGER, chunk_level TEXT, chunk_text TEXT)"
    )
    rag_tags.ensure_schema(conn)
    rows = [
        (1, "invoice.pdf", "", "", "document", "ok"),
        (2, "beach.jpg", "", "", "image", "ok"),
        (3, "receipt.jpg", "", "invoice", "image", "ok"),
        (4, "song.mp3", "", "", "audio", "ok"),
    ]
    conn.executemany("INSERT INTO indexed_files VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.executemany(
        "INSERT INTO document_chunks VALUES (?, 0, 'child', ?)",
        [(1, "Invoice. Amount due 20.00"), (2, "invoice invoice receipt"), (3, "Receipt total paid 9.90"), (4, "bill")],
    )
    assert rag_tags.backfill(conn) == 2
    done = {r[0] for r in conn.execute("SELECT file_id FROM doc_tags_done")}
    assert done == {1, 3}
    conn.close()


def test_the_chat_filters_on_the_tags_and_falls_back_without_them(monkeypatch):
    from backend.services import chat_nas_tools

    calls = []

    class Rag:
        def __init__(self, tagged):
            self.tagged = tagged

        def get_config(self):
            return {}

        def ask(self, **kw):
            calls.append(kw.get("tags"))
            hit = {"citations": [{"path": "/mnt/user/docs/invoice.pdf", "file_name": "invoice.pdf"}], "photos": []}
            return hit if (self.tagged or not kw.get("tags")) else {"citations": [], "photos": []}

    for tagged, want in ((True, [["bill", "year:2024"]]), (False, [["bill", "year:2024"], None])):
        rag = Rag(tagged)
        calls.clear()
        monkeypatch.setattr(chat_nas_tools, "_core", lambda rag=rag: SimpleNamespace(get_rag_engine=lambda: rag))
        chat_nas_tools.tool_search_nas_knowledge("show me my bills from 2024")
        assert calls == want
    calls.clear()
    chat_nas_tools.tool_search_nas_knowledge("what did the plumber say?")
    assert calls == [None]


def test_browsing_by_a_tag_needs_no_embedding_and_is_not_degraded(tmp_path, monkeypatch):
    from backend.services import rag_engine_search
    from backend.services.rag_engine import RagSearchEngine

    seen = []
    real = rag_engine_search.compute_multimodal_query_embedding

    def spy(**kw):
        seen.append(kw["model"])
        return real(**kw)

    monkeypatch.setattr(rag_engine_search, "compute_multimodal_query_embedding", spy)
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    try:
        res = engine.search(query="", tags=["bill"])
        assert seen == ["zett_lexical_384d"]
        assert not res.get("degraded")
    finally:
        engine.close()


def _wav_with_tags(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000 * 2)
    title, artist = b"Night Train\x00", b"The Testers\x00"

    def sub(tag, val):
        return tag + struct.pack("<I", len(val)) + val

    info = b"INFO" + sub(b"INAM", title) + sub(b"IART", artist)
    chunk = b"LIST" + struct.pack("<I", len(info)) + info
    data = path.read_bytes() + chunk
    path.write_bytes(data[:4] + struct.pack("<I", len(data) - 8) + data[8:])


def test_music_files_are_found_by_their_tags(tmp_path):
    from backend.services.rag_documents import extract_document_text

    song = tmp_path / "track01.wav"
    _wav_with_tags(song)
    text = extract_document_text(str(song), song.suffix)
    assert "Title: Night Train" in text and "Artist: The Testers" in text and "Duration: 0:02" in text


def test_audio_without_tags_still_gets_its_name(tmp_path):
    from backend.services.rag_documents import extract_document_text

    song = tmp_path / "broken.mp3"
    song.write_bytes(b"not audio")
    text = extract_document_text(str(song), song.suffix)
    assert "broken" in text


def test_the_ask_signature_takes_tags():
    import inspect

    from backend.services.rag_engine import RagSearchEngine

    assert "tags" in inspect.signature(RagSearchEngine.ask).parameters
