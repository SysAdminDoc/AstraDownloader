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
// the failures. Order matters in one place: the Python suite runs first so
// the Node tests can check the README's test count against what that run
// collected, rather than collecting the whole suite a second time.

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

// Both suites, named separately. "unit tests" used to mean only the Node
// files, which is how a red 1,262-test Python suite sat behind an "all gates
// passed" line: nothing in this command, `release:stage` or `build.py` ever
// ran pytest, and `documentation-facts` only ever collected it to count.
const GATES = [
    ['python suite', 'py', ['-3.13', '-m', 'pytest', '-q']],
    ['node tests', process.execPath, ['--test', ...TEST_FILES]],
    ['companion ports', process.execPath, ['scripts/check-companion-port-catalogue.js']],
    ['catch reasons', process.execPath, ['scripts/check-python-catch-reasons.js']],
    ['license inventory', process.execPath, ['scripts/check-companion-inventory.js']],
    ['site registry', 'py', ['-3.13', 'scripts/check-site-registry.py']],
    ['translations', 'py', ['-3.13', 'scripts/check-companion-translations.py']],
    ['versions', process.execPath, ['scripts/check-versions.js']],
    ['python audit', process.execPath, ['scripts/audit-python-deps.js']],
];

// conftest.py writes the collected count to this file when the variable names
// it, and tests/documentation-facts.test.js reads it back when it is set.
const COUNT_ENV = 'ASTRA_PYTEST_COUNT_FILE';
const COUNT_FILE = path.join(ROOT, 'build', 'pytest-collected.json');

// The Node tests only get the count file when the Python suite actually ran.
// A skipped suite leaves none, and the documentation test then collects for
// itself (and skips, since the interpreter is missing). The variable is never
// inherited from the caller's shell, which could point at a stale file.
function gateEnvironment(label, results) {
    const env = { ...process.env };
    delete env[COUNT_ENV];
    const suiteRan = results.some((result) => result.label === 'python suite' && !result.skipped);
    if (label === 'python suite' || (label === 'node tests' && suiteRan)) env[COUNT_ENV] = COUNT_FILE;
    return env;
}

function main() {
    const results = [];
    fs.rmSync(COUNT_FILE, { force: true });
    for (const [label, command, args] of GATES) {
        process.stdout.write(`\n──── ${label} ────\n`);
        const run = spawnSync(command, args, {
            cwd: ROOT, stdio: 'inherit', shell: false, env: gateEnvironment(label, results),
        });
        // A gate that could not be spawned at all is never a pass — an
        // uninstalled toolchain must not read as a green gate. A missing
        // interpreter is reported as SKIP with the reason named rather than a
        // bare exit 127, because "no CPython 3.13 on PATH" and "the suite
        // failed" want different responses. It still fails the command.
        const code = run.error ? 127 : (run.status === null ? 1 : run.status);
        // ENOENT is the rare case on Windows: the `py` launcher ships with any
        // Python install, so "no CPython 3.13" almost always surfaces as the
        // launcher's own exit 103, "No suitable Python runtime found". Reading
        // that as a plain FAIL makes a missing toolchain indistinguishable
        // from a failing suite, which is the distinction these gates exist to
        // draw. Either way it is never a pass.
        const missingTool = Boolean(run.error) && run.error.code === 'ENOENT';
        const noInterpreter = !run.error && code === 103 && command === 'py';
        const reason = missingTool
            ? `${command} is not on PATH`
            : (noInterpreter ? `${command} found no suitable Python runtime` : '');
        if (run.error && !missingTool) {
            process.stdout.write(`could not run ${command}: ${run.error.message}\n`);
        }
        const skipped = missingTool || noInterpreter;
        if (skipped) process.stdout.write(`skipped: ${reason}\n`);
        results.push({ label, code, skipped, reason });
    }

    const failed = results.filter((result) => result.code !== 0);
    process.stdout.write('\n──── summary ────\n');
    for (const { label, code, skipped, reason } of results) {
        if (code === 0) {
            process.stdout.write(`PASS  ${label}\n`);
        } else if (skipped) {
            process.stdout.write(`SKIP  ${label} (${reason})\n`);
        } else {
            process.stdout.write(`FAIL  ${label} (exit ${code})\n`);
        }
    }
    const broken = failed.filter((result) => !result.skipped);
    const unrun = failed.filter((result) => result.skipped);
    const parts = [];
    if (broken.length) parts.push(`${broken.length} failed: ${broken.map((r) => r.label).join(', ')}`);
    if (unrun.length) parts.push(`${unrun.length} could not run: ${unrun.map((r) => r.label).join(', ')}`);
    process.stdout.write(
        failed.length
            ? `\n${failed.length} of ${results.length} gates did not pass. ${parts.join('; ')}\n`
            : `\nall ${results.length} gates passed\n`
    );
    process.exitCode = failed.length ? 1 : 0;
}

if (require.main === module) main();

module.exports = { GATES, COUNT_ENV, gateEnvironment };
