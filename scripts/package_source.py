"""Build a source-only ZIP; never bundle local data, runtime or credentials."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FIXED = ('README.md', '.gitignore', 'requirements.txt', 'run.py',
         'config/local-llm.example.json', 'tools/dot-source-manifest.json')
TREES = {
    'acw': {'.py', '.png'},
    'docs': {'.md'},
    'scripts': {'.py', '.ps1', '.cs', '.manifest', '.md'},
    'tests': {'.py', '.md'},
    'tools/chatgpt-dot-cli-pinned': {'.py', '.md', '.toml', '.lock'},
    'tools/claude-session-sdk': {'.mjs', '.json', '.yaml'},
}
EXCLUDED = {'.git', '.venv', 'node_modules', '__pycache__', 'evidence', 'vendor'}
SECRET_NAMES = {'.env', 'auth.json', 'credentials.json', 'cookies.json', 'tokens.json',
                '.npmrc', '.pypirc', 'id_rsa', 'id_ed25519'}


def source_files(root):
    root = Path(root).resolve()
    files = []
    def regular(path):
        # Do not traverse symlinks or Windows junctions into local runtime/data.
        for part in (path, *path.parents):
            if part == root:
                break
            if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
                return False
        return path.is_file() and path.resolve().is_relative_to(root)
    for relative in FIXED:
        path = root / relative
        if not regular(path):
            raise ValueError('Required source missing or unsafe: ' + relative)
        files.append(path)
    for folder, extensions in TREES.items():
        base = root / folder
        if not base.is_dir() or base.is_symlink() or getattr(base, 'is_junction', lambda: False)():
            raise ValueError('Required source directory missing or unsafe: ' + folder)
        pending = [base]
        while pending:
            directory = pending.pop()
            for path in sorted(directory.iterdir()):
                if (path.name in EXCLUDED or path.name.lower() in SECRET_NAMES
                        or path.name.startswith('.env.') or path.is_symlink()
                        or getattr(path, 'is_junction', lambda: False)()):
                    continue
                if path.is_dir():
                    pending.append(path)
                elif path.suffix in extensions and regular(path):
                    files.append(path)
    for relative in ('tests/fixtures/g8-dot-contract-sample.json',
                     'tools/chatgpt-dot-cli-pinned/LICENSE'):
        path = root / relative
        if not regular(path):
            raise ValueError('Required fixture/license missing: ' + relative)
        files.append(path)
    return sorted(set(files))


def package(root, destination):
    root = Path(root).resolve()
    destination = Path(destination)
    if destination.suffix.lower() != '.zip':
        raise ValueError('Output must end in .zip')
    files = source_files(root)
    # Exclusive creation preserves previous packages, even on timestamp collisions.
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        entries = []
        for path in files:
            content = path.read_bytes()
            relative = path.relative_to(root).as_posix()
            archive.writestr(relative, content)
            entries.append({'path': relative, 'bytes': len(content),
                            'sha256': hashlib.sha256(content).hexdigest()})
        manifest = {
            'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'scope': 'Source only; no runtime, machine settings, user data or acceptance claim',
            'entrypoint': 'run.py', 'files': entries,
        }
        archive.writestr('SOURCE-MANIFEST.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP integrity check failed')
    return {'archive': str(destination.resolve()), 'files': len(entries),
            'bytes': destination.stat().st_size}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='New ZIP path; existing files are never overwritten')
    parser.add_argument('--list', action='store_true', help='List files without writing a ZIP')
    args = parser.parse_args(argv)
    if args.list:
        for path in source_files(ROOT):
            print(path.relative_to(ROOT).as_posix())
        return 0
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = args.output
    if output is None:
        folder = ROOT / 'evidence' / 'source-packages'
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / ('workspace-source-' + stamp + '.zip')
    print(json.dumps(package(ROOT, output), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
