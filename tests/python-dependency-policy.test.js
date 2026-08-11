'use strict';

// Moved here from the Astra Deck repository when Astra Downloader became its
// own product: these pin this repository's requirements graph and its Python
// dependency audit script.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');

const repoRoot = path.join(__dirname, '..');

test('requirements stay pinned for local companion dependency review', () => {
    const requirements = fs.readFileSync(
        path.join(repoRoot, 'astra_downloader', 'requirements.txt'), 'utf8'
    );
    assert.match(requirements, /^yt-dlp==\d{4}\.\d+\.\d+$/m,
        'yt-dlp must remain exactly pinned for reviewed local updates');
    assert.match(requirements, /^curl_cffi==\d+\.\d+\.\d+$/m,
        'curl_cffi must remain exactly pinned for reviewed local updates');
    assert.match(requirements, /^requests>=2\.33\.0,<3$/m,
        'Requests must exclude the vulnerable pre-2.33.0 range');
    assert.match(requirements, /^waitress>=3\.0\.2,<4$/m,
        'Waitress must exclude the vulnerable 3.0.0 and 3.0.1 releases');

    const constraints = fs.readFileSync(
        path.join(repoRoot, 'astra_downloader', 'constraints-release.txt'), 'utf8'
    );
    const pins = constraints.split(/\r?\n/)
        .map((line) => line.replace(/#.*/, '').trim())
        .filter(Boolean);
    assert.ok(pins.length >= 28, 'the reviewed release graph must include direct and transitive packages');
    assert.ok(pins.every((line) => /^[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+$/.test(line)),
        'every release constraint must be an exact name==version pin');
    assert.match(constraints, /^pyinstaller==6\.22\.0$/m,
        'the ambient PyInstaller version must be part of the reviewed graph');
    for (const retired of ['rich', 'markdown-it-py', 'Pygments', 'mdurl']) {
        assert.doesNotMatch(constraints, new RegExp(`^${retired}==`, 'mi'),
            `${retired} should not remain in the curl_cffi runtime graph`);
    }
});

test('Python companion audit emits release-review JSON and fails closed', () => {
    const audit = require(path.join(repoRoot, 'scripts', 'audit-python-deps.js'));
    assert.equal(
        audit.OUTPUT_PATH.endsWith(path.join('build', 'astra-downloader-pip-audit.json')),
        true,
        'Python audit must emit the named release-review artifact'
    );
    assert.equal(
        audit.RELEASE_CONSTRAINTS_PATH.endsWith(path.join('astra_downloader', 'constraints-release.txt')),
        true,
        'Python audit must include the exact reviewed release graph'
    );
    assert.equal(audit.FAILURE_FLOOR, 'moderate',
        'Python audit must fail moderate-or-higher findings');
    assert.equal(audit.isActionableSeverity('low'), false,
        'low-severity findings should not fail the release gate');
    assert.equal(audit.isActionableSeverity('unknown'), true,
        'unknown-severity findings must fail closed unless reviewed in code');

    const report = audit.normalizeAudit({
        dependencies: [{
            name: 'flask',
            version: '3.1.2',
            vulns: [{
                id: 'PYSEC-TEST-1',
                aliases: ['CVE-2099-0001'],
                severity: 'HIGH',
                fix_versions: ['3.1.3'],
                description: 'synthetic advisory'
            }]
        }]
    }, {
        now: new Date('2026-06-29T00:00:00.000Z')
    });
    assert.equal(report.status, 'fail',
        'unreviewed high-severity Python findings must fail the gate');
    assert.equal(report.summary.actionableFindings, 1);
    assert.equal(report.actionableFindings[0].package, 'flask');

    const minimum = audit.minimumRequirementsFor([
        'yt-dlp==2026.7.4',
        'PyQt6>=6.6.0,<7',
        'requests>=2.33.0,<3'
    ].join('\n'));
    assert.match(minimum, /^yt-dlp==2026\.7\.4$/m);
    assert.match(minimum, /^PyQt6==6\.6\.0$/m);
    assert.match(minimum, /^requests==2\.33\.0$/m);

    const combined = audit.combineAuditReports(
        { ...report, status: 'pass', actionableFindings: [], reviewedFindings: [] },
        report,
        { now: new Date('2026-07-14T00:00:00.000Z') }
    );
    assert.equal(combined.status, 'fail',
        'a vulnerability found only at the minimum resolution must fail the combined gate');
    assert.equal(combined.actionableFindings[0].resolution, 'minimum');

    const duplicate = audit.normalizeAudit({
        dependencies: [{
            name: 'requests',
            version: '2.32.4',
            vulns: [
                { id: 'PYSEC-TEST-2', aliases: ['CVE-2099-0002'], description: 'short' },
                { id: 'PYSEC-TEST-2', aliases: ['CVE-2099-0002'], description: 'longer duplicate' }
            ]
        }]
    });
    assert.equal(duplicate.summary.findings, 1,
        'duplicate records from advisory services must collapse to one finding');
    assert.equal(duplicate.actionableFindings[0].description, 'longer duplicate');

    const empty = audit.normalizeAudit({ dependencies: [] });
    assert.equal(empty.status, 'fail',
        'a zero-dependency audit result must not report a clean gate');
    assert.match(empty.auditErrors[0], /zero dependencies/);

    const nonZero = audit.normalizeAudit({
        dependencies: [{ name: 'requests', version: '2.33.0', vulns: [] }]
    }, { exitCode: 1 });
    assert.equal(nonZero.status, 'fail',
        'a non-zero pip-audit exit must fail even without parsed findings');

    const tempRequirements = path.join(require('os').tmpdir(), `astra-audit-${process.pid}.txt`);
    fs.writeFileSync(tempRequirements, 'requests>=2.33.0,<3\nflask>=3.1.3,<4\n');
    try {
        assert.throws(
            () => audit.assertAuditCoverage({ dependencies: [{ name: 'requests' }] }, tempRequirements),
            /omitted requirement\(s\): flask/
        );
    } finally {
        fs.rmSync(tempRequirements, { force: true });
    }
});
