"""Build a source/corpus deployment archive from an explicit allowlist.

Does not include local credentials, session databases, model weights or old logs.
The private deployment archive is never committed to the public repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', default='.build/e5/release.tar.gz')
    args = ap.parse_args()
    files = set()
    for folder in ['regnav', 'tests', 'scripts', 'eval', 'docs', 'deploy']:
        files.update(p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    for name in ['README.md', 'ROADMAP.md', 'requirements.txt', 'requirements-web.txt', 'constraints-web.txt',
                 'Dockerfile', '.dockerignore', '.env.example', 'compose.yaml', 'compose.local-model.yaml',
                 'compose.production.yaml', 'pytest.ini']:
        files.add(ROOT / name)
    for folder in ['raw', 'view']:
        files.update(p for p in (ROOT / 'data/official' / folder).rglob('*') if p.is_file())
    for name in ['manifest.jsonl', 'chunks.jsonl', 'revisions.json', 'ocr-corrections.json', 'import-report.json', 'e1-validation.json',
                 'e3-current-answer-report.json', 'e3-current-extra-report.json', 'e3-acceptance-report.json']:
        files.add(ROOT / 'data/official' / name)
    files.update(p for p in (ROOT / 'data/official/e5-checks').rglob('*') if p.is_file() and p.suffix not in {'.log'})
    for p in files:
        if p.is_symlink() or not p.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError('Unsafe release file: ' + str(p))
        if p.name == '.env' or p.suffix in {'.sqlite3', '.pem', '.key'}:
            raise ValueError('Private state in release: ' + str(p))
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    inventory = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    with tarfile.open(out, 'w:gz') as archive:
        for p in sorted(files):
            archive.add(p, arcname=p.relative_to(ROOT).as_posix(), recursive=False)
    receipt = {'archive_sha256': hashlib.sha256(out.read_bytes()).hexdigest(), 'files': inventory}
    out.with_suffix('.inventory.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(len(files), 'files;', out.stat().st_size, 'bytes;', receipt['archive_sha256'])


if __name__ == '__main__':
    main()
