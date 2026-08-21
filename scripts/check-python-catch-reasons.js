#!/usr/bin/env node
'use strict';

const { spawnSync } = require('child_process');
const path = require('path');

const repoRoot = path.join(__dirname, '..');
const defaultRoot = path.join(repoRoot, 'astra_downloader');
const requestedRoot = process.argv.indexOf('--root') >= 0
    ? process.argv[process.argv.indexOf('--root') + 1]
    : defaultRoot;

if (!requestedRoot || requestedRoot.startsWith('--')) {
    console.error('[check-python-catch-reasons] --root requires a directory');
    process.exit(2);
}

const checkSource = String.raw`
import ast
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
if not root.is_dir():
    print(f"[check-python-catch-reasons] root does not exist: {root}", file=sys.stderr)
    raise SystemExit(2)

reason_pattern = re.compile(r"#\s*reason\s*:\s*\S+", re.IGNORECASE)

# The gate used to look only at handlers whose body was nothing but \`pass\`,
# which let every \`return None\` / \`return ''\` / \`continue\` swallow through
# unexamined. What matters is not the shape of the body but whether anything
# outside the handler can tell the failure happened.
LOG_NAMES = {
    "log", "_log", "logger", "_logger", "logging",
    "debug", "info", "warning", "warn", "error", "exception", "critical",
    "print", "write_persistent_log", "append_log", "_append_log",
    "log_message", "_log_message", "emit",
}
BROAD_NAMES = {"Exception", "BaseException"}


def is_broad(handler):
    """A bare except, or one that names Exception/BaseException."""
    node = handler.type
    if node is None:
        return True
    items = [node] if not isinstance(node, ast.Tuple) else list(node.elts)
    for item in items:
        if (getattr(item, "attr", None) or getattr(item, "id", None)) in BROAD_NAMES:
            return True
    return False


def reports_the_failure(handler):
    """True when something outside the handler can still see it happened.

    Three ways count: re-raising, calling something from the logging
    vocabulary, or binding the exception and using it - a handler that turns
    the error into a message it returns has reported it, just not to a log.
    """
    if handler.name:
        for inner in ast.walk(handler):
            if isinstance(inner, ast.Name) and inner.id == handler.name:
                return True
    for inner in ast.walk(handler):
        if isinstance(inner, ast.Raise):
            return True
        if isinstance(inner, ast.Call):
            func = inner.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name and name.lower() in LOG_NAMES:
                return True
    return False


def is_pass_only(handler):
    return all(isinstance(statement, ast.Pass) for statement in handler.body)


def silent_handlers(tree):
    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler) or not handler.body:
            continue
        # Pass-only handlers stay in scope whatever they catch - that was the
        # original rule and a narrow one still discards the failure entirely.
        if not (is_broad(handler) or is_pass_only(handler)):
            continue
        if reports_the_failure(handler):
            continue
        yield handler


violations = []
count = 0
for path in sorted(root.rglob("*.py")):
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        print(f"[check-python-catch-reasons] syntax error in {path}: {error}", file=sys.stderr)
        raise SystemExit(2)
    lines = source.splitlines()
    for handler in silent_handlers(tree):
        count += 1
        end_line = handler.end_lineno or handler.lineno
        snippet = "\n".join(lines[handler.lineno - 1:end_line])
        if not reason_pattern.search(snippet):
            violations.append(f"{path.relative_to(root.parent).as_posix()}:{handler.lineno}")

if violations:
    print(
        "[check-python-catch-reasons] Missing '# reason:' on broad exception "
        "handlers that neither log nor re-raise:"
    )
    for violation in violations:
        print(f"  - {violation}")
    raise SystemExit(1)

print(f"[check-python-catch-reasons] OK - {count} silent exception handler(s) carry a reason")
`;

const candidates = process.platform === 'win32'
    ? [
        { command: 'py', prefix: ['-3.13'] },
        { command: 'python', prefix: [] },
        { command: 'python3', prefix: [] },
    ]
    : [
        { command: process.env.ASTRA_PYTHON || 'python3', prefix: [] },
        { command: 'python', prefix: [] },
    ];

let unavailable = true;
for (const candidate of candidates) {
    const result = spawnSync(
        candidate.command,
        [...candidate.prefix, '-c', checkSource, path.resolve(repoRoot, requestedRoot)],
        { cwd: repoRoot, encoding: 'utf8' },
    );
    if (result.error && result.error.code === 'ENOENT') continue;
    unavailable = false;
    if (result.stdout) process.stdout.write(result.stdout);
    if (result.stderr) process.stderr.write(result.stderr);
    process.exit(result.status === null ? 2 : result.status);
}

if (unavailable) {
    console.error('[check-python-catch-reasons] no usable Python interpreter was found');
    process.exit(2);
}
