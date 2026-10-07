'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const repoRoot = path.resolve(__dirname, '..');
const readme = fs.readFileSync(path.join(repoRoot, 'README.md'), 'utf8');
const building = fs.readFileSync(path.join(repoRoot, 'docs/BUILDING.md'), 'utf8');
const documentation = readme + '\n' + building;
const packageJson = require(path.join(repoRoot, 'package.json'));
const heroReference = '![Astra Downloader for Windows with the Download queue and format controls](assets/marketing/social-card-dark.png)';

function pythonCandidates() {
    return process.platform === 'win32'
        ? [{ command: 'py', prefix: ['-3.13'] }, { command: 'python', prefix: [] }]
        : [{ command: process.env.ASTRA_PYTHON || 'python3', prefix: [] }];
}

test('the README leads with one evergreen marketing hero', () => {
    assert.ok(readme.startsWith(heroReference), 'the selected hero must be the first README content');
    assert.equal(
        readme.split('assets/marketing/social-card-dark.png').length - 1,
        1,
        'the selected hero must appear exactly once in the README',
    );

    const source = fs.readFileSync(
        path.join(repoRoot, 'assets', 'marketing', 'social-card.html'), 'utf8',
    );
    assert.doesNotMatch(source, /\bv\d+\.\d+\.\d+\b/i, 'hero source must not carry a release number');
    assert.match(
        source,
        /transform:translateX\(-120px\)/,
        'the hero must crop the version-bearing app sidebar from its product preview',
    );

    const png = fs.readFileSync(
        path.join(repoRoot, 'assets', 'marketing', 'social-card-dark.png'),
    );
    assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
    assert.equal(png.readUInt32BE(16), 1280, 'hero width');
    assert.equal(png.readUInt32BE(20), 640, 'hero height');
});

// Windows answers `python` with an App Execution Alias even when no CPython
// is installed: it spawns, prints the Microsoft Store notice and exits 9009,
// so spawn reports no error. The `py` launcher's equivalent is exit 103,
// "No suitable Python runtime found". Both mean "no interpreter here", the
// same thing ENOENT means, and neither is a broken suite.
const STORE_ALIAS_NOTICE = /Microsoft Store|App execution aliases/i;
const COLLECTED_COUNT = /^(\d+) tests collected/m;

function isMissingInterpreter(candidate, result) {
    if (result.status === 0) return false;
    const output = `${result.stdout || ''}${result.stderr || ''}`;
    if (STORE_ALIAS_NOTICE.test(output)) return true;
    return candidate.command === 'py' && result.status === 103;
}

function collectPytestCount(candidates = pythonCandidates(), spawn = spawnSync) {
    let ran = false;
    let lastOutput = '';
    for (const candidate of candidates) {
        const result = spawn(
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
        const match = COLLECTED_COUNT.exec(result.stdout || '');
        if (match) return { ran: true, collected: Number(match[1]), output: '' };
        if (isMissingInterpreter(candidate, result)) continue;
        ran = true;
        lastOutput = `${result.stdout || ''}${result.stderr || ''}`;
    }
    return { ran, collected: null, output: lastOutput };
}

function verifyStatedCount(probe, text = documentation) {
    if (!probe.ran) {
        console.log('[documentation-facts] no Python interpreter; skipping the count check');
        return 'skipped';
    }
    assert.ok(
        probe.collected !== null,
        'pytest ran but reported no collected count:\n' + probe.output.slice(-2000),
    );
    const stated = /py -3\.\d+ -m pytest(?: -rs)?\s+# (\d[\d,]*) tests/.exec(text);
    assert.ok(stated, 'The build guide must state the count beside the pytest command');
    assert.equal(
        Number(stated[1].replace(/,/g, '')), probe.collected,
        `README says ${stated[1]} tests, pytest collects ${probe.collected}`,
    );
    return 'verified';
}

// A stated count in a README is a fact with a shelf life. Reading it back off
// the command the README tells you to run is the only way it stays true; every
// previous pass left the number behind and the next reader trusted it.
test('the documented test count is the count pytest collects', () => {
    verifyStatedCount(collectPytestCount());
});

function fakeSpawn(results) {
    return (command) => {
        const result = results[command];
        assert.ok(result, `unexpected interpreter ${command}`);
        return { error: null, stdout: '', stderr: '', ...result };
    };
}

const WINDOWS_CANDIDATES = [{ command: 'py', prefix: ['-3.13'] }, { command: 'python', prefix: [] }];

test('the Store python alias and a launcher with no runtime skip the count check', () => {
    const probe = collectPytestCount(WINDOWS_CANDIDATES, fakeSpawn({
        py: { status: 103, stderr: 'No suitable Python runtime found\n' },
        python: {
            status: 9009,
            stderr: 'Python was not found; run without arguments to install from the Microsoft Store, ' +
                'or disable this shortcut from Settings > Apps > Advanced app settings > App execution aliases.\n',
        },
    }));
    assert.equal(probe.ran, false);
    assert.equal(verifyStatedCount(probe), 'skipped');
});

test('a pytest that fails collection still fails the count check', () => {
    const probe = collectPytestCount(WINDOWS_CANDIDATES, fakeSpawn({
        py: {
            status: 2,
            stdout: 'ERROR astra_downloader/test_gui.py - ImportError: cannot import name\n' +
                '!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!\n',
        },
        python: {
            status: 9009,
            stderr: 'Python was not found; run without arguments to install from the Microsoft Store.\n',
        },
    }));
    assert.equal(probe.ran, true);
    assert.throws(() => verifyStatedCount(probe), /pytest ran but reported no collected count[\s\S]*1 error during collection/);
});

test('documented commands are commands the project defines', () => {
    assert.match(readme, /\]\(docs\/BUILDING\.md\)/, 'README must link to the build guide');
    const fenced = documentation.match(/```powershell\n([\s\S]*?)```/g) || [];
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

test('the build guide describes the gate set npm run check actually runs', () => {
    const { GATES } = require(path.join(repoRoot, 'scripts', 'run-checks.js'));
    assert.ok(GATES.length >= 5, 'the gate table must be readable from run-checks.js');
    const word = GATE_COUNT_WORDS[GATES.length];
    assert.ok(word, `no spelled form for ${GATES.length} gates`);
    // Derived rather than hardcoded: the count used to be the literal 8 in
    // both this test and the README, so adding a gate meant editing the
    // assertion that was supposed to catch the drift.
    assert.match(
        documentation,
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
