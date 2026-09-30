// Fixed helpers for explicitly non-isolated local development.
const GLOB_SCRIPT = String.raw`
import glob
import os
import sys
from pathlib import Path

root = Path(os.environ.get('ATOM_WORKSPACE_ROOT', '/workspace')).resolve()
pattern = sys.argv[1]
limit = int(sys.argv[2])
matches = set()
for raw in glob.iglob(pattern, root_dir=str(root), recursive=True, include_hidden=True):
    candidate = (root / raw).resolve()
    if candidate.is_relative_to(root):
        matches.add(Path(raw).as_posix())
    if len(matches) >= limit:
        break
print('\n'.join(sorted(matches)) if matches else '(no matches)')
`.trim();

const GREP_SCRIPT = String.raw`
import os
import re
import sys
from pathlib import Path, PurePosixPath

root = Path(os.environ.get('ATOM_WORKSPACE_ROOT', '/workspace')).resolve()
expression = sys.argv[1]
relative_base = sys.argv[2]
include = sys.argv[3] or None
case_sensitive = sys.argv[4] == '1'
limit = int(sys.argv[5])
base = (root / relative_base).resolve()
if not base.is_relative_to(root):
    raise SystemExit('path escapes the workspace')
if not base.exists():
    raise SystemExit(f'path not found: {relative_base}')
matcher = re.compile(expression, 0 if case_sensitive else re.IGNORECASE)

def candidates():
    if base.is_file():
        yield base
        return
    for directory, directories, files in os.walk(base, followlinks=False):
        directories[:] = [
            name for name in directories
            if name not in {'.git', 'node_modules'} and not (Path(directory) / name).is_symlink()
        ]
        for name in files:
            yield Path(directory) / name

matches = []
for candidate in candidates():
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        continue
    relative = resolved.relative_to(root).as_posix()
    if include and not PurePosixPath(relative).match(include):
        continue
    try:
        if resolved.stat().st_size > 1_048_576:
            continue
        with resolved.open('rb') as stream:
            data = stream.read(1_048_577)
        if len(data) > 1_048_576:
            continue
        text = data.decode('utf-8', errors='replace')
    except OSError:
        continue
    for line_number, line in enumerate(text.splitlines(), 1):
        if matcher.search(line):
            matches.append(f'{relative}:{line_number}:{line}')
            if len(matches) >= limit:
                break
    if len(matches) >= limit:
        break
print('\n'.join(matches) if matches else '(no matches)')
`.trim();

const READ_FILE_SCRIPT = String.raw`
import os
import sys
from pathlib import Path

root = Path(os.environ.get('ATOM_WORKSPACE_ROOT', '/workspace')).resolve()
relative = sys.argv[1]
start = int(sys.argv[2])
limit = int(sys.argv[3])
target = (root / relative).resolve()
if not target.is_relative_to(root):
    raise SystemExit('path escapes the workspace')
if not target.is_file():
    raise SystemExit(f'file not found: {relative}')
with target.open('rb') as stream:
    data = stream.read(8 * 1024 * 1024 + 1)
if len(data) > 8 * 1024 * 1024:
    raise SystemExit('file exceeds 8 MiB')
lines = data.decode('utf-8', errors='replace').splitlines()
selected = lines[start - 1:start - 1 + limit]
print('\n'.join(selected) if selected else '(empty range)')
`.trim();

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

function pythonCommand(script: string, args: Array<string | number>): string {
  return ['"${ATOM_PYTHON_EXECUTABLE:-python3}"', '-c', shellQuote(script), ...args.map((value) => shellQuote(String(value)))].join(' ');
}


export function localTextCommand(operation: import('../packages/product-contracts/src/index.ts').WorkspaceFileOperation): string {
  switch (operation.op) {
    case 'glob': return pythonCommand(GLOB_SCRIPT, [operation.pattern, operation.limit]);
    case 'grep': return pythonCommand(GREP_SCRIPT, [operation.pattern, operation.path, operation.glob, operation.case_sensitive ? 1 : 0, operation.limit]);
    case 'read_lines': return pythonCommand(READ_FILE_SCRIPT, [operation.path, operation.start, operation.limit]);
    default: throw new Error('Unsupported local text operation');
  }
}
