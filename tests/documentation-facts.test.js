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

const GATE_COUNT_WORDS = [
    'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight',
    'nine', 'ten', 'eleven', 'twelve',
];

test('the README describes the gate set npm run check actually runs', () => {
    const { GATES } = require(path.join(repoRoot, 'scripts', 'run-checks.js'));
    assert.ok(GATES.length >= 5, 'the gate table must be readable from run-checks.js');
    const word = GATE_COUNT_WORDS[GATES.length];
    assert.ok(word, `no spelled form for ${GATES.length} gates`);
    // Derived rather than hardcoded: the count used to be the literal 8 in
    // both this test and the README, so adding a gate meant editing the
    // assertion that was supposed to catch the drift.
    assert.match(
        readme,
        new RegExp(`all ${word} gates`),
        `run-checks.js declares ${GATES.length} gates; the README must say "all ${word} gates"`,
    );
});

// The gate named for a suite has to run it. "unit tests" once meant only the
// six Node files, so a red Python suite of 1,262 tests sat behind an "all
// gates passed" line for as long as nobody ran pytest by hand.
test('npm run check actually executes the Python suite', () => {
    const { GATES } = require(path.join(repoRoot, 'scripts', 'run-checks.js'));
    const pytestGates = GATES.filter(
        ([, , args]) => args.includes('pytest') || args.includes('-m') && args.includes('pytest'),
    );
    assert.equal(
        pytestGates.length, 1,
        'exactly one gate must run pytest; found ' +
        JSON.stringify(GATES.map(([label]) => label)),
    );
    const [label, , args] = pytestGates[0];
    assert.ok(
        !args.includes('--collect-only'),
        `the ${label} gate collects the suite instead of running it`,
    );
    assert.ok(
        !GATES.some(([name]) => name === 'unit tests'),
        'a gate called "unit tests" hides which suite it runs; name the suite',
    );
});
