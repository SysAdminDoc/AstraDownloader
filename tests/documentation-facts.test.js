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
    for (const candidate of pythonCandidates()) {
        const result = spawnSync(
            candidate.command,
            [...candidate.prefix, '-m', 'pytest', '--collect-only', '-q'],
            { cwd: repoRoot, encoding: 'utf8' },
        );
        if (result.error || result.status !== 0) continue;
        const match = /^(\d+) tests collected/m.exec(result.stdout || '');
        if (match) {
            collected = Number(match[1]);
            break;
        }
    }
    if (collected === null) {
        // Same posture as the other Python-backed gates: an absent interpreter
        // is not a documentation failure.
        console.log('[documentation-facts] no usable Python; skipping the count check');
        return;
    }

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
        /all seven gates/,
        'the README must name how many gates npm run check runs',
    );
    assert.equal(
        declared, 7,
        `the README says seven gates; run-checks.js declares ${declared}`,
    );
});
