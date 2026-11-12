import json
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from openpyxl import Workbook
import pymupdf

from regnav.core.extract import extract
from regnav.core.ingest import build_chunks, build_texts
from regnav.core.search import HybridSearcher


def manifest(root, paths):
    records = [{"id": p.stem, "title": p.stem, "local_path": p.name,
                "url": "https://example.org/" + p.name} for p in paths]
    (root / "manifest.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def ingest(root):
    build_texts(root, workers=1)
    chunks = build_chunks(root)
    report = json.loads((root / "import-report.json").read_text(encoding="utf-8"))
    return chunks, report


def test_office_order_and_formula_cache(tmp_path):
    path = tmp_path / "procedure.docx"
    doc = Document()
    doc.add_heading("Приложение 1", 1)
    doc.add_paragraph("1. Порядок оформления заявки")
    table = doc.add_table(rows=1, cols=3)
    for cell, text in zip(table.rows[0].cells, ["Заявка на командировку", "42", "42"]):
        cell.text = text
    doc.add_heading("Приложение 2", 1)
    doc.add_paragraph("1. Другая процедура")
    merged = doc.add_table(rows=2, cols=2)
    merged.cell(0, 0).merge(merged.cell(1, 0)).text = "Вертикальная ячейка"
    doc.save(path)
    result = extract(path)
    texts = [b["text"] for b in result["blocks"]]
    assert texts.count("42") == 2
    assert texts.count("Вертикальная ячейка") == 1
    assert texts.index("Заявка на командировку") < texts.index("Приложение 2")

    book_path = tmp_path / "budget.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Смета"
    sheet.append(["Статья расходов", "Сумма"])
    sheet.append(["Командировки", 100])
    sheet["B3"] = "=SUM(B2:B2)"
    sheet["B4"] = "=B3*2"
    sheet.merge_cells("A5:B5")
    sheet["A5"] = "Примечание"
    book.save(book_path)
    # Simulate an actual persisted Excel calculation result, including zero handling.
    with ZipFile(book_path) as source:
        members = {n: source.read(n) for n in source.namelist()}
    members["xl/worksheets/sheet1.xml"] = members["xl/worksheets/sheet1.xml"].replace(
        b'<f>SUM(B2:B2)</f><v></v>', b'<f>SUM(B2:B2)</f><v>100</v>')
    with ZipFile(book_path, "w", ZIP_DEFLATED) as target:
        for name, content in members.items():
            target.writestr(name, content)
    extracted = extract(book_path)
    assert extracted["formula_count"] == 2
    assert extracted["missing_formula_values"] == ["Смета!B4"]
    formula = next(b for b in extracted["blocks"] if "B3:B3" == b["range"])
    assert formula["cells"][0]["cached_value"] == 100
    assert extracted["sheets"][0]["merged_ranges"] == ["A5:B5"]
    manifest(tmp_path, [path, book_path])
    chunks, report = ingest(tmp_path)
    assert report["summary"]["error"] == 0
    assert {c.doc_id for c in chunks} == {"procedure", "budget"}
    assert any("42" in c.text and "tbl" in " ".join(c.meta["source_locations"]) for c in chunks if c.doc_id == "procedure")
    assert HybridSearcher(chunks).search("Командировки сумма", k=3)
    assert any("прил. 1" in c.clause for c in chunks if "Заявка" in c.text)


def test_corrupt_repaired_changed_and_stable_ids(tmp_path):
    good = tmp_path / "good.docx"
    broken = tmp_path / "broken.pdf"
    doc = Document()
    doc.add_paragraph("1. Подача заявления на командировку")
    doc.save(good)
    broken.write_bytes(b"not a PDF")
    manifest(tmp_path, [good, broken])
    chunks, report = ingest(tmp_path)
    assert report["summary"]["error"] == 1
    assert {c.doc_id for c in chunks} == {"good"}
    initial_ids = [c.chunk_id for c in chunks]
    chunks, report = ingest(tmp_path)
    assert initial_ids == [c.chunk_id for c in chunks]
    assert report["files"][0]["cached"]
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((50, 50), "Repaired source document with sufficient native text for extraction.")
    pdf.save(broken)
    pdf.close()
    chunks, report = ingest(tmp_path)
    assert report["summary"]["error"] == 0
    assert {c.doc_id for c in chunks} == {"good", "broken"}
    assert [c.chunk_id for c in chunks if c.doc_id == "good"] == initial_ids
    good.write_bytes(b"broken replacement")
    chunks, report = ingest(tmp_path)
    assert report["summary"]["error"] == 1
    assert not any(c.doc_id == "good" for c in chunks)
    assert not (tmp_path / "extracted/good.json").exists()


def test_new_files_each_format_appear_in_search_and_cli_errors(tmp_path):
    from regnav.__main__ import main
    paths = []
    doc = Document()
    doc.add_paragraph("Кадровый подбор персонала")
    path = tmp_path / "hr.docx"
    doc.save(path)
    paths.append(path)
    manifest(tmp_path, paths)
    ingest(tmp_path)
    workbook = Workbook()
    workbook.active["A1"] = "Бюджетная финансовая смета"
    path = tmp_path / "budget.xlsx"
    workbook.save(path)
    paths.append(path)
    document = pymupdf.open()
    document.new_page().insert_text((40, 60), "Datacenter technical operation procedure and maintenance regulations.")
    path = tmp_path / "datacenter.pdf"
    document.save(path)
    document.close()
    paths.append(path)
    manifest(tmp_path, paths)
    chunks, report = ingest(tmp_path)
    assert report["summary"]["error"] == 0
    searcher = HybridSearcher(chunks)
    for query, doc_id in [("подбор персонала", "hr"), ("финансовая смета", "budget"), ("Datacenter maintenance", "datacenter")]:
        assert searcher.search(query, k=1)[0].chunk.doc_id == doc_id
    paths[2].write_bytes(b"corrupt PDF")
    assert main(["--data", str(tmp_path), "ingest", "--workers", "1"]) == 1


def test_pdf_ocr_path_preserves_pages(tmp_path, monkeypatch):
    """Deterministic OCR branch test; real Russian OCR is verified on the official corpus."""
    path = tmp_path / "scan.pdf"
    pdf = pymupdf.open()
    pdf.new_page()
    pdf.save(path)
    pdf.close()
    called = []
    def ocr(page, **kwargs):
        called.append(kwargs)
        return page.get_textpage()
    monkeypatch.setattr(pymupdf.Page, "get_textpage_ocr", ocr)
    original = pymupdf.Page.get_text
    def text(page, *args, **kwargs):
        return "Распознанная заявка на командировку" if "textpage" in kwargs else original(page, *args, **kwargs)
    monkeypatch.setattr(pymupdf.Page, "get_text", text)
    result = extract(path)
    assert result["ocr_pages"] == [1]
    assert result["blocks"][0]["locator"] == "page=1"
    assert called[0]["language"] == "rus"
