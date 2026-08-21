#!/usr/bin/env node
'use strict';

// `npm run check` used to be an `&&` chain. That made the first red gate hide
// every gate behind it: when the license inspection was wired up and started
// failing, the port catalogue, catch-reason, translation, version and
// pip-audit gates stopped running entirely, and nobody could tell whether they
// were green or had been broken for weeks. A gate you cannot see the result of
// is not a gate.
//
// Every gate now runs, every result is printed, and the exit code is the OR of
// the failures. Order still matters for readability, not for control flow.

const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');

// Every test file, discovered rather than listed. A hand-kept list means a new
// suite is written, passes when run directly, and is never reached by the
// command the docs tell you to run - which is how three of them ended up
// outside `npm run check`.
const TEST_FILES = fs.readdirSync(path.join(ROOT, 'tests'))
    .filter((name) => name.endsWith('.test.js'))
    .sort()
    .map((name) => path.posix.join('tests', name));

if (!TEST_FILES.length) {
    console.error('[run-checks] no test files found under tests/');
    process.exit(2);
}

const GATES = [
    ['unit tests', process.execPath, ['--test', ...TEST_FILES]],
    ['companion ports', process.execPath, ['scripts/check-companion-port-catalogue.js']],
    ['catch reasons', process.execPath, ['scripts/check-python-catch-reasons.js']],
    ['license inventory', process.execPath, ['scripts/check-companion-inventory.js']],
    ['translations', 'py', ['-3.13', 'scripts/check-companion-translations.py']],
    ['versions', process.execPath, ['scripts/check-versions.js']],
    ['python audit', process.execPath, ['scripts/audit-python-deps.js']],
];

function main() {
    const results = [];
    for (const [label, command, args] of GATES) {
        process.stdout.write(`\n──── ${label} ────\n`);
        const run = spawnSync(command, args, { cwd: ROOT, stdio: 'inherit', shell: false });
        // A gate that could not be spawned at all (missing interpreter) is a
        // failure, not a skip — otherwise an uninstalled toolchain reads as a
        // pass.
        const code = run.error ? 127 : (run.status === null ? 1 : run.status);
        if (run.error) process.stdout.write(`could not run ${command}: ${run.error.message}\n`);
        results.push({ label, code });
    }

    const failed = results.filter((result) => result.code !== 0);
    process.stdout.write('\n──── summary ────\n');
    for (const { label, code } of results) {
        process.stdout.write(`${code === 0 ? 'PASS' : 'FAIL'}  ${label}${code === 0 ? '' : ` (exit ${code})`}\n`);
    }
    process.stdout.write(
        failed.length
            ? `\n${failed.length} of ${results.length} gates failed: ${failed.map((r) => r.label).join(', ')}\n`
            : `\nall ${results.length} gates passed\n`
    );
    process.exitCode = failed.length ? 1 : 0;
}

if (require.main === module) main();

module.exports = { GATES };
