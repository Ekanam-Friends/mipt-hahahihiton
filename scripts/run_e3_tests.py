"""Run pytest and retain stdout, exit status and exact tested file hashes."""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E3_TESTS = ['tests/test_core.py', 'tests/test_ingest.py', 'tests/test_e2.py',
            'tests/test_e3.py', 'tests/test_e3_acceptance.py']


def snapshot():
    paths = sorted((ROOT / 'regnav/core').glob('*.py'))
    paths += [ROOT / 'regnav/__init__.py', ROOT / 'regnav/__main__.py']
    paths += [ROOT / name for name in E3_TESTS]
    paths += [ROOT / 'scripts/apply_e3_reviews.py', ROOT / 'scripts/verify_e3.py']
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    started = datetime.now(timezone.utc)
    before = snapshot()
    command = [sys.executable, '-X', 'utf8', '-m', 'pytest', '-q', *E3_TESTS, *sys.argv[1:]]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    after = snapshot()
    runner_code = result.returncode if result.returncode else 0 if before == after else 2
    record = {'started_at': started.isoformat(), 'finished_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'E3 core and CLI regressions; independently changing E4 web files excluded',
              'command': command, 'returncode': result.returncode, 'stdout': result.stdout,
              'stderr': result.stderr, 'files_sha256': before, 'snapshot_stable': before == after,
              'files_sha256_after': after, 'runner_returncode': runner_code,
              'changed_files': [name for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)],
              'passed': result.returncode == 0 and before == after}
    folder = ROOT / 'data/official/e3-unit-runs'
    folder.mkdir(exist_ok=True)
    path = folder / (started.strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, file=sys.stderr, end='')
    print('Saved:', path.relative_to(ROOT), 'stable snapshot:', record['snapshot_stable'])
    return runner_code


if __name__ == '__main__':
    raise SystemExit(main())
