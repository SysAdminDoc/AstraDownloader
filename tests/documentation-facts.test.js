'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const repoRoot = path.resolve(__dirname, '..');
const readme = fs.readFileSync(path.join(repoRoot, 'README.md'), 'utf8');
const packageJson = require(path.join(repoRoot, 'package.json'));

function pythonCandidates() {
    return process.platform === 'win32'
        ? [{ command: 'py', prefix: ['-3.13'] }, { command: 'python', prefix: [] }]
        : [{ command: process.env.ASTRA_PYTHON || 'python3', prefix: [] }];
}

// A stated count in a README is a fact with a shelf life. Reading it back off
// the command the README tells you to run is the only way it stays true; every
// previous pass left the number behind and the next reader trusted it.
test('the test count the README states is the count pytest collects', () => {
    let collected = null;
    let ran = false;
    let lastOutput = '';
    for (const candidate of pythonCandidates()) {
        const result = spawnSync(
            candidate.command,
            [...candidate.prefix, '-m', 'pytest', '--collect-only', '-q'],
            { cwd: repoRoot, encoding: 'utf8' },
        );
        // An absent interpreter is not a documentation failure. Anything else
        // is: a collection error, a broken conftest or a bad addopts line used
        // to read as "no Python" and turn this gate green while the README was
        // provably wrong.
        if (result.error) {
            if (result.error.code === 'ENOENT') continue;
            throw result.error;
        }
        ran = true;
        lastOutput = `${result.stdout || ''}${result.stderr || ''}`;
        const match = /^(\d+) tests collected/m.exec(result.stdout || '');
        if (match) {
            collected = Number(match[1]);
            break;
        }
    }
    if (!ran) {
        console.log('[documentation-facts] no Python interpreter; skipping the count check');
        return;
    }
    assert.ok(
        collected !== null,
        'pytest ran but reported no collected count:\n' + lastOutput.slice(-2000),
    );

    const stated = /py -3\.\d+ -m pytest\s+# (\d[\d,]*) tests/.exec(readme);
    assert.ok(stated, 'README must state the test count beside the pytest command');
    assert.equal(
        Number(stated[1].replace(/,/g, '')), collected,
        `README says ${stated[1]} tests, pytest collects ${collected}`,
    );
});

test('the commands the README shows are commands the project defines', () => {
    const fenced = readme.match(/```powershell\n([\s\S]*?)```/g) || [];
    const npmRuns = new Set();
    for (const block of fenced) {
        for (const line of block.split('\n')) {
            const match = /^npm run ([\w:-]+)/.exec(line.trim());
            if (match) npmRuns.add(match[1]);
        }
    }
    assert.ok(npmRuns.size >= 3, 'the README must show the project commands');
    for (const script of npmRuns) {
        assert.ok(
            Object.hasOwn(packageJson.scripts, script),
            `README shows \`npm run ${script}\` but package.json does not define it`,
        );
    }
});

test('the README describes the gate set npm run check actually runs', () => {
    const gates = fs.readFileSync(path.join(repoRoot, 'scripts', 'run-checks.js'), 'utf8');
    const declared = (gates.match(/^\s*\['([a-z][\w -]*)',/gm) || []).length;
    assert.ok(declared >= 5, 'the gate table must be readable from run-checks.js');
    assert.match(
        readme,
        /all eight gates/,
        'the README must name how many gates npm run check runs',
    );
    assert.equal(
        declared, 8,
        `the README says eight gates; run-checks.js declares ${declared}`,
    );
});
