"""AI-9: office documents, e-books and e-mail are read for the AI index."""

import zipfile

from backend.services import rag_office
from backend.services.rag_documents import extract_document_text


def _zip(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return str(path)


def test_xlsx_rows_with_shared_strings(tmp_path):
    p = _zip(
        tmp_path / "budget.xlsx",
        {
            "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="March" sheetId="1"/></sheets></workbook>',
            "xl/sharedStrings.xml": '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Holiday deposit</t></si><si><t>Cornwall cottage</t></si></sst>',
            "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            '<row><c t="s"><v>0</v></c><c><v>300</v></c><c t="s"><v>1</v></c></row></sheetData></worksheet>',
        },
    )
    text = extract_document_text(p, ".xlsx")
    assert "## March" in text and "Holiday deposit | 300 | Cornwall cottage" in text


def test_pptx_slides_and_notes(tmp_path):
    a = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    p = _zip(
        tmp_path / "talk.pptx",
        {
            "ppt/slides/slide2.xml": f"<sld {a}><a:p><a:r><a:t>Budget for Q2</a:t></a:r></a:p></sld>",
            "ppt/slides/slide1.xml": f"<sld {a}><a:p><a:r><a:t>Welcome</a:t></a:r></a:p></sld>",
            "ppt/notesSlides/notesSlide1.xml": f"<notes {a}><a:p><a:r><a:t>Say hello</a:t></a:r></a:p></notes>",
        },
    )
    text = extract_document_text(p, ".pptx")
    assert text.index("Welcome") < text.index("Budget for Q2") < text.index("Say hello")


def test_odt_headings_paragraphs_and_tables(tmp_path):
    ns = 'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
    p = _zip(
        tmp_path / "minutes.odt",
        {
            "content.xml": f"<doc {ns}><text:h>Meeting</text:h><text:p>Lift replaced in spring.</text:p>"
            "<table:table><table:table-row><table:table-cell><text:p>Cost</text:p></table:table-cell>"
            "<table:table-cell><text:p>1200</text:p></table:table-cell></table:table-row></table:table></doc>",
        },
    )
    text = extract_document_text(p, ".odt")
    assert "# Meeting" in text and "Lift replaced in spring." in text and "Cost | 1200" in text


def test_epub_follows_the_spine(tmp_path):
    p = _zip(
        tmp_path / "book.epub",
        {
            "META-INF/container.xml": '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
            "OEBPS/content.opf": '<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>Garden Year</dc:title></metadata>'
            '<manifest><item id="c1" href="ch1.xhtml"/><item id="c2" href="ch2.xhtml"/></manifest>'
            '<spine><itemref idref="c2"/><itemref idref="c1"/></spine></package>',
            "OEBPS/ch1.xhtml": "<html><body><p>Prune roses in March.</p></body></html>",
            "OEBPS/ch2.xhtml": "<html><body><p>Plant bulbs in autumn.</p><script>x()</script></body></html>",
        },
    )
    text = extract_document_text(p, ".epub")
    assert "Title: Garden Year" in text
    assert text.index("Plant bulbs") < text.index("Prune roses") and "x()" not in text


def test_eml_headers_body_and_attachment_names(tmp_path):
    p = tmp_path / "invoice.eml"
    p.write_bytes(
        b"From: Shop <shop@example.com>\r\nTo: me@example.com\r\nSubject: Your invoice 1042\r\n"
        b"MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=XX\r\n\r\n"
        b"--XX\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nTotal due: 89.90 EUR by 1 May.\r\n"
        b"--XX\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename=invoice-1042.pdf\r\n\r\nJVBERi0=\r\n--XX--\r\n"
    )
    text = extract_document_text(str(p), ".eml")
    assert "Subject: Your invoice 1042" in text and "89.90 EUR" in text and "invoice-1042.pdf" in text


def test_mbox_reads_each_message(tmp_path):
    p = tmp_path / "inbox.mbox"
    p.write_text(
        "From a@example.com Mon Jan  1 00:00:00 2025\nSubject: Boiler service\n\nEngineer comes on 12 Oct.\n\n"
        "From b@example.com Mon Jan  2 00:00:00 2025\nSubject: School trip\n\nBad Toelz in May.\n"
    )
    text = extract_document_text(str(p), ".mbox")
    assert "Boiler service" in text and "Bad Toelz in May." in text


def test_rtf_words(tmp_path):
    p = tmp_path / "letter.rtf"
    p.write_text(r"{\rtf1\ansi{\fonttbl{\f0 Arial;}}\f0\fs24 Dear neighbour,\par the caf\'e9 opens at 9.\par}")
    text = extract_document_text(str(p), ".rtf")
    assert "Dear neighbour," in text and "café opens at 9." in text and "Arial" not in text


def test_oversized_parts_are_not_expanded(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_office, "MAX_MEMBER_BYTES", 1000)
    p = _zip(tmp_path / "big.odt", {"content.xml": "<doc>" + "<p>a</p>" * 500 + "</doc>"})
    assert extract_document_text(p, ".odt") == ""
