"""Run inside the built image with --network none; writes a portable smoke report.

docker run --rm --network none -v ./scripts:/qa:ro -v ./data/official/e4-checks:/out regnav:e4 python /qa/verify_e4_container.py
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path.cwd()))


def main():
    import pymupdf
    from docx import Document
    from openpyxl import Workbook
    from regnav.core.ingest import build_texts, build_chunks
    checks = []
    with tempfile.TemporaryDirectory() as temporary:
        data = Path(temporary)
        raw = data / 'raw'
        raw.mkdir()
        pdf = pymupdf.open()
        page = pdf.new_page()
        page.insert_text((40, 80), 'Регламент подачи заявки. Заявитель направляет форму в учебный офис.',
                         fontname='demo', fontfile='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', fontsize=14)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
        scan = pymupdf.open()
        scan.new_page(width=page.rect.width, height=page.rect.height).insert_image(page.rect, pixmap=pixmap)
        scan.save(raw / 'scan.pdf')
        scan.close()
        pdf.close()
        doc = Document()
        doc.add_heading('Порядок оформления заявки', 0)
        doc.add_paragraph('Заявитель направляет заполненную форму в учебный офис в течение трёх рабочих дней.')
        doc.save(raw / 'form.docx')
        workbook = Workbook()
        workbook.active.append(['Наименование', 'Сумма'])
        workbook.active.append(['Заявка', 100])
        workbook.active['B3'] = '=SUM(B2:B2)'
        workbook.save(raw / 'cost.xlsx')
        records = [{'id':path.stem, 'title':path.name, 'local_path':str(path)} for path in raw.iterdir()]
        (data / 'manifest.jsonl').write_text('\n'.join(json.dumps(record, ensure_ascii=False) for record in records), encoding='utf-8')
        build_texts(data, workers=1)
        chunks = build_chunks(data)
        report = json.loads((data / 'import-report.json').read_text(encoding='utf-8'))
        assert report['summary']['error'] == 0, report
        assert {chunk.doc_id for chunk in chunks} == {'scan', 'form', 'cost'}
        scanned = json.loads((data / 'extracted/scan.json').read_text(encoding='utf-8'))
        assert scanned['ocr_pages'] == [1] and scanned['blocks'][0]['text'].strip()
        checks += ['fresh PDF scan OCR with rus language', 'fresh DOCX/XLSX import, formulas, HTML views']
        # A bad document produces an explicit import error, rather than a false success.
        (raw / 'broken.pdf').write_bytes(b'not a PDF')
        with (data / 'manifest.jsonl').open('a', encoding='utf-8') as handle:
            handle.write('\n' + json.dumps({'id':'broken', 'title':'Broken', 'local_path':str(raw / 'broken.pdf')}))
        build_texts(data, workers=1)
        build_chunks(data)
        broken_report = json.loads((data / 'import-report.json').read_text(encoding='utf-8'))
        assert broken_report['summary']['error'] == 1
        checks.append('corrupt PDF yields explicit per-file error')
    languages = subprocess.check_output(['tesseract', '--list-langs'], text=True)
    assert 'rus' in languages and 'eng' in languages
    assert os.getuid() != 0
    result = {'checks':checks, 'uid':os.getuid(), 'ocr_languages':languages.splitlines(),
              'import_summary':report['summary'], 'broken_import_summary':broken_report['summary'],
              'network':'container launched with --network none'}
    output = Path('/out')
    output.mkdir(exist_ok=True)
    (output / 'container.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
