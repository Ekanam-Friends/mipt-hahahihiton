"""Inspect every reachable Git revision without printing potential secret values.

This is a pattern and filename audit, not a guarantee against all secret formats.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{24,}|-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----|sk-proj-[A-Za-z0-9_-]{30,})')
BAD_NAMES = re.compile(r'(^|/)(\.env|id_ed25519|id_rsa|authorized_keys|accounts\.sqlite3)$|\.(pem|key|p12|pfx|dump)$')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    commits = git('rev-list', '--all').decode().splitlines()
    objects = {}
    paths = []
    for commit in commits:
        for row in git('ls-tree', '-r', '-z', commit).split(b'\0'):
            if not row:
                continue
            metadata, name = row.split(b'\t', 1)
            mode, kind, oid = metadata.split()
            name = name.decode('utf-8', errors='replace')
            if BAD_NAMES.search(name):
                paths.append({'commit': commit, 'path': name, 'reason': 'private_filename'})
            if kind == b'blob':
                objects.setdefault(oid.decode(), set()).add(name)
    findings = []
    for oid, names in objects.items():
        data = git('cat-file', 'blob', oid)
        matches = PATTERNS.findall(data)
        if matches:
            findings.append({'object': oid, 'paths': sorted(names), 'matches': len(matches)})
    current = set(git('ls-files', '-z').split(b'\0')) | set(git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0'))
    working_findings = []
    for raw in current:
        if not raw:
            continue
        name = raw.decode('utf-8')
        path = ROOT / name
        if not path.is_file():
            continue
        if BAD_NAMES.search(name) or PATTERNS.search(path.read_bytes()):
            working_findings.append({'path': name, 'reason': 'private_filename_or_credential_pattern'})
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'commits': len(commits),
              'unique_blobs': len(objects), 'filename_findings': paths, 'credential_pattern_findings': findings,
              'working_files': len(current) - (b'' in current), 'working_findings': working_findings,
              'passed': not paths and not findings and not working_findings,
              'limitations': 'Reachable Git history, selected credential formats and private filenames only. Does not scan remote service settings, deleted unreachable objects or all possible credentials.'}
    out = ROOT / 'data/official/e5-checks/public-audit.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return int(not report['passed'])


if __name__ == '__main__':
    raise SystemExit(main())
