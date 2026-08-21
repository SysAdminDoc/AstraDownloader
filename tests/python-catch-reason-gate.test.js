const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const test = require('node:test');

const repoRoot = path.resolve(__dirname, '..');
const gate = path.join(repoRoot, 'scripts', 'check-python-catch-reasons.js');

function runGate(root) {
    return execFileSync(
        process.execPath,
        root ? [gate, '--root', root] : [gate],
        { cwd: repoRoot, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
    );
}

function expectRejection(root, fixture, line) {
    fs.writeFileSync(path.join(root, 'fixture.py'), fixture, 'utf8');
    assert.throws(
        () => runGate(root),
        (error) => error.status === 1
            && /Missing '# reason:'/.test(`${error.stdout}${error.stderr}`)
            && new RegExp(`fixture\\.py:${line}`).test(`${error.stdout}${error.stderr}`),
        `expected the gate to reject fixture.py:${line}`,
    );
}

test('Python catch-reason gate accepts the companion tree', () => {
    assert.match(runGate(), /silent exception handler\(s\) carry a reason/);
});

test('Python catch-reason gate rejects an unreasoned pass-only handler', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-python-catch-'));
    try {
        // A narrow catch that discards the failure entirely stays in scope.
        expectRejection(root, 'try:\n    raise OSError()\nexcept OSError:\n    pass\n', 3);
    } finally {
        fs.rmSync(root, { recursive: true, force: true });
    }
});

test('Python catch-reason gate rejects a broad handler that swallows without passing', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-python-catch-'));
    try {
        // The shapes the pass-only rule never examined.
        expectRejection(root, 'def f():\n    try:\n        g()\n    except Exception:\n        return None\n', 4);
        expectRejection(root, 'def f():\n    try:\n        g()\n    except Exception:\n        return \'\'\n', 4);
        expectRejection(root, 'def f():\n    for x in y:\n        try:\n            g()\n        except Exception:\n            continue\n', 5);
        expectRejection(root, 'def f():\n    try:\n        g()\n    except:\n        return 0\n', 4);
    } finally {
        fs.rmSync(root, { recursive: true, force: true });
    }
});

test('Python catch-reason gate accepts a handler that reports the failure', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-python-catch-'));
    try {
        const accepted = [
            // Re-raised.
            'def f():\n    try:\n        g()\n    except Exception:\n        raise\n',
            // Logged.
            'def f():\n    try:\n        g()\n    except Exception:\n        self._logger("broke")\n',
            // Bound and carried into what the caller gets back.
            'def f():\n    try:\n        g()\n    except Exception as error:\n        return None, str(error)\n',
            // Annotated.
            'def f():\n    try:\n        g()\n    except Exception:\n        # reason: an absent value is the answer\n        return None\n'
        ];
        for (const fixture of accepted) {
            fs.writeFileSync(path.join(root, 'fixture.py'), fixture, 'utf8');
            assert.match(runGate(root), /carry a reason/);
        }
    } finally {
        fs.rmSync(root, { recursive: true, force: true });
    }
});
