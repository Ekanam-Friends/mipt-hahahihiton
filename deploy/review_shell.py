"""Restricted read-only viewer, run inside a container without host/network access."""
from collections import deque
import hashlib
import os
from pathlib import Path
import shlex
import sys

ROOT = Path('/project').resolve()
current = ROOT
HELP = 'Commands: pwd, cd PATH, ls [PATH], cat FILE, head [-n N] FILE, tail [-n N] FILE, grep TEXT FILE, find [PATH], wc FILE, sha256sum FILE, help, exit. No pipes, shell expansion, writes or external commands.'


def target(value='.'):
    raw = Path(value)
    path = (raw if raw.is_absolute() else current / raw).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Only /project is accessible')
    if not path.exists():
        raise ValueError('Path does not exist')
    return path


def text(path):
    if not path.is_file():
        raise ValueError('Expected a regular file')
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('File exceeds 2 MiB viewer limit')
    data = path.read_bytes()
    if b'\0' in data:
        raise ValueError('Binary file; use sha256sum or inspect its source manifest')
    return data.decode('utf-8', errors='replace')


def run(command):
    global current
    parts = shlex.split(command)
    if not parts:
        return
    if len(command) > 4096 or any(x in command for x in ['\x00', '\x1b']):
        raise ValueError('Invalid command')
    name, args = parts[0], parts[1:]
    if name in {'exit', 'quit'} and not args:
        raise EOFError
    if name == 'help' and not args:
        print(HELP)
    elif name == 'pwd' and not args:
        print(current)
    elif name == 'cd' and len(args) <= 1:
        path = target(args[0] if args else '/project')
        if not path.is_dir():
            raise ValueError('Not a directory')
        current = path
    elif name == 'ls' and len(args) <= 1:
        path = target(args[0] if args else '.')
        children = sorted(path.iterdir()) if path.is_dir() else [path]
        for child in children[:1000]:
            print(child.name + ('/' if child.is_dir() else ''))
    elif name == 'find' and len(args) <= 1:
        base = target(args[0] if args else '.')
        for i, path in enumerate(base.rglob('*')):
            if i >= 1000:
                print('[1000 entries limit]')
                break
            print(path.relative_to(ROOT))
    elif name in {'cat', 'wc', 'sha256sum'} and len(args) == 1:
        path = target(args[0])
        if name == 'sha256sum':
            if not path.is_file():
                raise ValueError('Expected a regular file')
            h = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(65536), b''):
                    h.update(block)
            print(h.hexdigest(), path)
        else:
            content = text(path)
            if name == 'cat':
                print(content)
            else:
                print(len(content.splitlines()), len(content.split()), len(content.encode('utf-8')), path)
    elif name in {'head', 'tail'}:
        count = 20
        if len(args) == 3 and args[0] == '-n':
            count = int(args[1])
            args = args[2:]
        if len(args) != 1 or not 1 <= count <= 1000:
            raise ValueError('Use head/tail [-n 1..1000] FILE')
        content = text(target(args[0])).splitlines()
        print('\n'.join(content[:count] if name == 'head' else content[-count:]))
    elif name == 'grep' and len(args) == 2:
        for n, line in enumerate(text(target(args[1])).splitlines(), 1):
            if args[0] in line:
                print(str(n) + ':' + line)
    else:
        raise ValueError('Command is not permitted. ' + HELP)


def main():
    os.umask(0o077)
    if len(sys.argv) > 1 and sys.argv[1]:
        try:
            run(sys.argv[1])
        except (ValueError, OSError, EOFError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0
    print('MIPT review terminal. /project is read-only.\n' + HELP)
    while True:
        try:
            run(input(str(current) + '> '))
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        except (ValueError, OSError) as exc:
            print('Error:', str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
