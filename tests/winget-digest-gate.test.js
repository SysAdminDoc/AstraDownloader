'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
    readWingetInstallerSha256,
    updateWingetManifestDigest,
    wingetDigestFailures
} = require('../scripts/stage-companion-release');

const VERSION = '9.9.9';
const DIGEST = 'a'.repeat(63) + 'b';

function manifestText(digest) {
    return [
        'PackageIdentifier: SysAdminDoc.AstraDownloader',
        `PackageVersion: ${VERSION}`,
        'InstallerType: portable',
        'Installers:',
        '- Architecture: x64',
        `  InstallerUrl: https://github.com/SysAdminDoc/AstraDownloader/releases/download/v${VERSION}/AstraDownloader.exe`,
        `  InstallerSha256: ${digest}`,
        'ManifestType: installer',
        ''
    ].join('\n');
}

function stagedMetadata(digest) {
    return { version: VERSION, artifact: { sha256: digest } };
}

test('staging writes the staged digest into the manifest', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'winget-digest-'));
    const manifestPath = path.join(dir, 'SysAdminDoc.AstraDownloader.installer.yaml');
    fs.writeFileSync(manifestPath, manifestText('0'.repeat(64)), 'utf8');

    updateWingetManifestDigest(VERSION, DIGEST.toUpperCase(), manifestPath);

    const written = readWingetInstallerSha256(fs.readFileSync(manifestPath, 'utf8'));
    assert.strictEqual(written, DIGEST, 'the digest is written lowercased from the artifact');
    fs.rmSync(dir, { recursive: true, force: true });
});

test('staging refuses a manifest that is missing or has no digest field', () => {
    assert.throws(
        () => updateWingetManifestDigest(VERSION, DIGEST, path.join(os.tmpdir(), 'no-such-manifest.yaml')),
        /missing/
    );
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'winget-digest-'));
    const manifestPath = path.join(dir, 'SysAdminDoc.AstraDownloader.installer.yaml');
    fs.writeFileSync(manifestPath, 'PackageVersion: 9.9.9\n', 'utf8');
    assert.throws(() => updateWingetManifestDigest(VERSION, DIGEST, manifestPath), /InstallerSha256/);
    fs.rmSync(dir, { recursive: true, force: true });
});

test('a matching staged digest passes the gate', () => {
    assert.deepStrictEqual(
        wingetDigestFailures(manifestText(DIGEST), VERSION, stagedMetadata(DIGEST.toUpperCase())),
        []
    );
});

test('mutating one byte of the manifest digest fails the gate', () => {
    const mutated = DIGEST.slice(0, -1) + 'c';
    const failures = wingetDigestFailures(manifestText(mutated), VERSION, stagedMetadata(DIGEST));
    assert.strictEqual(failures.length, 1);
    assert.match(failures[0], /does not match the staged/);
    assert.match(failures[0], /release:stage/);
});

test('a staged build for a different version is not comparable and not a failure', () => {
    assert.deepStrictEqual(
        wingetDigestFailures(manifestText(DIGEST), VERSION, { version: '1.0.0', artifact: { sha256: '0'.repeat(64) } }),
        []
    );
    assert.deepStrictEqual(wingetDigestFailures(manifestText(DIGEST), VERSION, null), []);
});

test('a manifest with no parseable digest is itself a failure', () => {
    const failures = wingetDigestFailures('PackageVersion: 9.9.9\n', VERSION, stagedMetadata(DIGEST));
    assert.strictEqual(failures.length, 1);
    assert.match(failures[0], /64-digit hex digest/);
});
