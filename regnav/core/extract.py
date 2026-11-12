"""Local extraction preserving source locations; never executes Office content."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

VERSION = 2


def extract(path: Path, dpi: int = 300) -> dict:
    result = {"version": VERSION, "blocks": [], "warnings": [], "ocr_pages": [],
              "empty_pages": [], "pages": 0, "formula_count": 0, "missing_formula_values": []}
    blocks = result["blocks"]
    if path.suffix.lower() == ".pdf":
        import pymupdf
        tdir = os.environ.get("TESSERACT_DIR", r"C:\Program Files\Tesseract-OCR")
        if not shutil.which("tesseract") and Path(tdir, "tesseract.exe").exists():
            os.environ["PATH"] += os.pathsep + tdir
        tessdata = str(Path(os.environ.get("TESSDATA_DIR", ".tessdata")).resolve())
        with pymupdf.open(path) as document:
            result["pages"] = len(document)
            for number, page in enumerate(document, 1):
                text = page.get_text("text", sort=True)
                if len(text.strip()) < 40:
                    tp = page.get_textpage_ocr(language="rus", dpi=dpi, full=True, tessdata=tessdata)
                    text = page.get_text("text", textpage=tp, sort=True)
                    result["ocr_pages"].append(number)
                if not text.strip():
                    result["empty_pages"].append(number)
                blocks.append({"text": text, "page": number, "locator": f"page={number}"})
    elif path.suffix.lower() == ".docx":
        from docx import Document
        from docx.text.paragraph import Paragraph
        document = Document(path)

        def walk(parent, prefix):
            for pos, element in enumerate(parent, 1):
                tag = element.tag.rsplit("}", 1)[-1]
                location = f"{prefix}/{tag}[{pos}]"
                if tag == "p":
                    paragraph = Paragraph(element, document)
                    if paragraph.text.strip():
                        blocks.append({"text": paragraph.text, "locator": location,
                                       "style": paragraph.style.name if paragraph.style else ""})
                elif tag == "tbl":
                    # Traverse physical XML cells: row.cells repeats vertical merges.
                    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                    for row_no, row in enumerate(element.findall(namespace + "tr"), 1):
                        for col_no, cell in enumerate(row.findall(namespace + "tc"), 1):
                            walk(cell, f"{location}/row[{row_no}]/cell[{col_no}]")
                elif tag in {"sdt", "sdtContent"}:
                    walk(element, location)
        walk(document.element.body, "body")
    elif path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        formulas = load_workbook(path, data_only=False, keep_links=False)
        values = load_workbook(path, data_only=True, keep_links=False)
        try:
            result["sheets"] = []
            for sheet in formulas:
                result["sheets"].append({"name": sheet.title, "state": sheet.sheet_state,
                                         "merged_ranges": [str(r) for r in sheet.merged_cells.ranges]})
                for row in sheet:
                    cells, texts = [], []
                    for cell in row:
                        if cell.value is None:
                            continue
                        value = cell.value
                        item = {"address": cell.coordinate, "value": str(value)}
                        if cell.data_type == "f":
                            result["formula_count"] += 1
                            cached = values[sheet.title][cell.coordinate].value
                            item.update(formula=str(value), cached_value=cached)
                            if cached is None:
                                result["missing_formula_values"].append(f"{sheet.title}!{cell.coordinate}")
                            value = f"формула {value}; сохранённое значение: {cached if cached is not None else 'отсутствует'}"
                        cells.append(item)
                        texts.append(f"{cell.coordinate}: {value}")
                    if cells:
                        address = f"{cells[0]['address']}:{cells[-1]['address']}"
                        blocks.append({"text": f"Лист «{sheet.title}», {address}: " + " | ".join(texts),
                                       "locator": f"'{sheet.title}'!{address}", "sheet": sheet.title,
                                       "range": address, "cells": cells})
        finally:
            formulas.close()
            values.close()
    else:
        raise ValueError(f"неподдерживаемый формат: {path.suffix}")
    if result["empty_pages"]:
        result["warnings"].append("Пустые страницы после OCR: " + str(result["empty_pages"]))
    if result["missing_formula_values"]:
        result["warnings"].append(f"Нет сохранённого значения у {len(result['missing_formula_values'])} формул; вычисление не выполнялось")
    if not any(b["text"].strip() for b in blocks):
        raise ValueError("Не извлечено непустого текста")
    return result
