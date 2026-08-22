'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const {
    assetName,
    digestForAsset,
    pinnedSources,
    resolveRuntimeHelpers
} = require('../scripts/resolve-runtime-helpers');
const { inspectCompanionInventory, PROPERTY } = require('../scripts/companion-license-inventory');

const DIGEST = 'a'.repeat(64);

test('checksum sidecars are read in every shape the three publishers ship', () => {
    const sums = [
        '1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6  yt-dlp',
        `${DIGEST}  yt-dlp.exe`,
        '072aad4f2a7604e92155f61a275a4752dc64046c8f6d90df3710525d94cd37c1  yt-dlp.tar.gz'
    ].join('\n');
    assert.equal(digestForAsset(sums, 'yt-dlp.exe'), DIGEST);
    assert.equal(digestForAsset(sums, 'yt-dlp_arm64.exe'), null,
        'an asset the sidecar does not name must not borrow another entry');

    const starred = `${DIGEST} *ffmpeg-master-latest-win64-gpl.zip`;
    assert.equal(digestForAsset(starred, 'ffmpeg-master-latest-win64-gpl.zip'), DIGEST);

    // Deno publishes the console rendering of PowerShell's Get-FileHash, so
    // the digest and the filename arrive on separate lines.
    const getFileHash = [
        'Algorithm : SHA256',
        `Hash      : ${DIGEST.toUpperCase()}`,
        'Path      : C:\\a\\deno\\deno\\target\\release\\deno-x86_64-pc-windows-msvc.zip'
    ].join('\r\n');
    assert.equal(digestForAsset(getFileHash, 'deno-x86_64-pc-windows-msvc.zip'), DIGEST);
    assert.equal(digestForAsset(getFileHash, 'deno-aarch64-pc-windows-msvc.zip'), null);
});

test('a Get-FileHash sidecar covering two assets keeps them apart', () => {
    const other = 'b'.repeat(64);
    const twoBlocks = [
        'Algorithm : SHA256',
        `Hash      : ${DIGEST.toUpperCase()}`,
        'Path      : C:\\out\\deno-x86_64-pc-windows-msvc.zip',
        '',
        'Algorithm : SHA256',
        `Hash      : ${other.toUpperCase()}`,
        'Path      : C:\\out\\deno-aarch64-pc-windows-msvc.zip'
    ].join('\r\n');
    assert.equal(digestForAsset(twoBlocks, 'deno-x86_64-pc-windows-msvc.zip'), DIGEST);
    assert.equal(digestForAsset(twoBlocks, 'deno-aarch64-pc-windows-msvc.zip'), other);

    // A stray Path line must not re-point the digest above it at another file.
    const strayPath = [
        'Algorithm : SHA256',
        `Hash      : ${DIGEST.toUpperCase()}`,
        'Path      : C:\\out\\SOMETHING-ELSE.zip',
        'Path      : C:\\out\\deno-x86_64-pc-windows-msvc.zip'
    ].join('\r\n');
    assert.equal(digestForAsset(strayPath, 'deno-x86_64-pc-windows-msvc.zip'), null);
});

test('a bare digest counts only when the sidecar filename names the asset', () => {
    const url = 'https://example.test/releases/download/v1/tool.zip.sha256';
    assert.equal(digestForAsset(DIGEST, 'tool.zip', url), DIGEST);
    assert.equal(digestForAsset(DIGEST, 'other.zip', url), null);
    assert.equal(digestForAsset(DIGEST, 'tool.zip'), null,
        'without the sidecar URL nothing ties those bytes to that download');
});

test('asset names come from the distribution URL path', () => {
    assert.equal(
        assetName('https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe'),
        'yt-dlp.exe'
    );
    assert.equal(
        assetName('https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'),
        'ffmpeg-master-latest-win64-gpl.zip'
    );
});

test('resolution writes the version and digest back into the policy', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-helper-resolve-'));
    const policyPath = path.join(dir, 'license-policy.json');
    fs.writeFileSync(policyPath, JSON.stringify({
        schemaVersion: 1,
        components: {},
        runtimeHelpers: [
            {
                key: 'yt-dlp',
                name: 'yt-dlp.exe',
                version: 'unresolved',
                licenseReviewed: true,
                decision: 'unresolved',
                resolution: 'The moving latest URL must be resolved.',
                distributionUrl: 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe',
                checksumUrl: 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS',
                sourceUrl: 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.tar.gz',
                noticeUrl: 'https://github.com/yt-dlp/yt-dlp#license',
                obligations: ['Retain the notice.']
            },
            {
                key: 'quickjs',
                name: 'QuickJS-ng runtime',
                version: '0.16.1',
                decision: 'approved',
                pinnedInSource: true,
                sha256: 'b'.repeat(64),
                distributionUrl: 'https://example.test/releases/download/v0.16.1/qjs.exe',
                checksumUrl: '',
                sourceUrl: 'https://example.test/quickjs',
                noticeUrl: 'https://example.test/quickjs/LICENSE',
                obligations: ['Retain the MIT notice.']
            }
        ]
    }, null, 2) + '\n');

    const originalFetch = global.fetch;
    global.fetch = async (url) => {
        if (String(url).includes('api.github.com')) {
            return new Response(JSON.stringify({ tag_name: '2026.08.19' }), { status: 200 });
        }
        return new Response(`${DIGEST}  yt-dlp.exe\n`, { status: 200 });
    };
    try {
        const resolved = await resolveRuntimeHelpers(policyPath);
        assert.deepEqual(resolved, ['yt-dlp=2026.08.19']);
    } finally {
        global.fetch = originalFetch;
    }

    const policy = JSON.parse(fs.readFileSync(policyPath, 'utf8'));
    const ytdlp = policy.runtimeHelpers.find((helper) => helper.key === 'yt-dlp');
    assert.equal(ytdlp.version, '2026.08.19');
    assert.equal(ytdlp.sha256, DIGEST);
    assert.equal(ytdlp.decision, 'approved');
    assert.match(ytdlp.approvalEvidence, /yt-dlp\.exe at 2026\.08\.19 is SHA-256 a{64}/);
    assert.equal('resolution' in ytdlp, false,
        'a resolved helper must not keep the sentence describing why it was not');
    assert.equal(
        ytdlp.sourceUrl,
        'https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/yt-dlp.tar.gz',
        'the corresponding-source link must name the version the entry records',
    );

    const quickjs = policy.runtimeHelpers.find((helper) => helper.key === 'quickjs');
    assert.equal(quickjs.sha256, 'b'.repeat(64),
        'a source-pinned helper is not re-resolved over the network');
});

function helperComponent(overrides) {
    const properties = {
        [PROPERTY.componentKey]: 'yt-dlp',
        [PROPERTY.delivery]: 'runtime-download',
        [PROPERTY.decision]: 'approved',
        [PROPERTY.evidence]: 'resolved at staging',
        [PROPERTY.sourceUrl]: 'https://github.com/yt-dlp/yt-dlp',
        [PROPERTY.noticeUrl]: 'https://github.com/yt-dlp/yt-dlp#license',
        [PROPERTY.obligations]: JSON.stringify(['Retain the notice.']),
        [PROPERTY.artifactSha256]: DIGEST,
        [PROPERTY.checksumUrl]: 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS',
        [PROPERTY.distributionUrl]: 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe',
        [PROPERTY.downloadSha256]: DIGEST,
        ...overrides
    };
    return {
        type: 'application',
        name: 'yt-dlp.exe',
        version: '2026.08.19',
        licenses: [{ expression: 'GPL-3.0-or-later' }],
        properties: Object.entries(properties).map(([name, value]) => ({ name, value: String(value) }))
    };
}

test('a rolling alias passes only once staging has resolved it to a digest', () => {
    const resolved = inspectCompanionInventory({ components: [helperComponent({})] }, DIGEST);
    assert.deepEqual(
        resolved.issues.filter((issue) => /yt-dlp/.test(issue)),
        [],
        'a latest URL backed by a resolved digest is the reviewed delivery form'
    );

    const unresolved = inspectCompanionInventory(
        { components: [helperComponent({ [PROPERTY.downloadSha256]: '' })] },
        DIGEST
    );
    assert.ok(unresolved.issues.some((issue) => /yt-dlp: exact download SHA-256 is unresolved/.test(issue)));
    assert.ok(unresolved.issues.some((issue) => /yt-dlp: distribution URL still uses a moving latest target/.test(issue)),
        'without the digest the moving alias is still named as the problem it is');
});

test('a helper nobody has reviewed is not approved by running staging', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-helper-review-'));
    const policyPath = path.join(dir, 'license-policy.json');
    fs.writeFileSync(policyPath, JSON.stringify({
        schemaVersion: 1,
        components: {},
        runtimeHelpers: [{
            key: 'newcomer',
            name: 'newcomer.exe',
            version: 'unresolved',
            licenseExpression: 'GPL-3.0-or-later',
            decision: 'unresolved',
            distributionUrl: 'https://github.com/example/newcomer/releases/latest/download/newcomer.exe',
            checksumUrl: 'https://github.com/example/newcomer/releases/latest/download/SHA2-256SUMS',
            sourceUrl: 'https://github.com/example/newcomer',
            noticeUrl: 'https://github.com/example/newcomer#license',
            obligations: ['Retain the notice.']
        }]
    }, null, 2) + '\n');

    const originalFetch = global.fetch;
    global.fetch = async () => {
        throw new Error('resolution must not reach the network for an unreviewed helper');
    };
    try {
        await assert.rejects(
            () => resolveRuntimeHelpers(policyPath),
            /awaiting a human licence review: newcomer/
        );
    } finally {
        global.fetch = originalFetch;
    }

    const policy = JSON.parse(fs.readFileSync(policyPath, 'utf8'));
    assert.equal(policy.runtimeHelpers[0].decision, 'unresolved',
        'staging must not decide a licence question on its own');
});

test('a resolved digest does not excuse a moving corresponding-source link', () => {
    const movingSource = inspectCompanionInventory({
        components: [helperComponent({
            [PROPERTY.sourceUrl]: 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.tar.gz'
        })]
    }, DIGEST);
    assert.ok(
        movingSource.issues.some((issue) => /yt-dlp: source URL still uses a moving latest target/.test(issue)),
        'the digest pins the download, not the GPL corresponding source'
    );

    const pinnedSource = inspectCompanionInventory({
        components: [helperComponent({
            [PROPERTY.sourceUrl]: 'https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/yt-dlp.tar.gz'
        })]
    }, DIGEST);
    assert.deepEqual(pinnedSource.issues.filter((issue) => /yt-dlp/.test(issue)), []);
});

test('a pinned helper resolves the pinned release, not the rolling alias', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-pinned-helper-'));
    const policyPath = path.join(dir, 'license-policy.json');
    fs.writeFileSync(policyPath, JSON.stringify({
        runtimeHelpers: [
            {
                key: 'yt-dlp',
                name: 'yt-dlp.exe',
                version: 'unresolved',
                licenseReviewed: true,
                decision: 'unresolved',
                pinnedVersion: '2026.07.04',
                pinnedDistributionUrl:
                    'https://github.com/yt-dlp/yt-dlp/releases/download/2026.07.04/yt-dlp.exe',
                pinnedChecksumUrl:
                    'https://github.com/yt-dlp/yt-dlp/releases/download/2026.07.04/SHA2-256SUMS',
                distributionUrl: 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe',
                checksumUrl: 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS',
                sourceUrl: 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.tar.gz',
                noticeUrl: 'https://github.com/yt-dlp/yt-dlp#license',
                obligations: ['Retain the notice.']
            }
        ]
    }, null, 2) + '\n');

    const requested = [];
    const originalFetch = global.fetch;
    global.fetch = async (url) => {
        requested.push(String(url));
        return new Response(`${DIGEST}  yt-dlp.exe\n`, { status: 200 });
    };
    try {
        assert.deepEqual(await resolveRuntimeHelpers(policyPath), ['yt-dlp=2026.07.04']);
    } finally {
        global.fetch = originalFetch;
    }

    assert.deepEqual(requested, [
        'https://github.com/yt-dlp/yt-dlp/releases/download/2026.07.04/SHA2-256SUMS'
    ], 'a pinned helper must not ask GitHub what latest points at');

    const helper = JSON.parse(fs.readFileSync(policyPath, 'utf8')).runtimeHelpers[0];
    assert.equal(helper.version, '2026.07.04');
    assert.equal(helper.sha256, DIGEST);
    assert.equal(helper.decision, 'approved');
    assert.match(helper.approvalEvidence, /Pinned rather than resolved from a rolling alias/);
    assert.match(helper.approvalEvidence, /this inventory neither reads nor constrains/,
        'the evidence must not claim a link between a policy pin and the running app');
    assert.equal(
        helper.distributionUrl,
        'https://github.com/yt-dlp/yt-dlp/releases/download/2026.07.04/yt-dlp.exe',
        'a pinned digest beside a rolling alias reads as a resolved alias'
    );
    assert.equal(
        helper.checksumUrl,
        'https://github.com/yt-dlp/yt-dlp/releases/download/2026.07.04/SHA2-256SUMS'
    );
    assert.match(helper.approvalEvidence, /2026\.07\.04 is SHA-256 a{64}/);
    assert.equal(
        helper.sourceUrl,
        'https://github.com/yt-dlp/yt-dlp/releases/download/2026.07.04/yt-dlp.tar.gz',
        'the corresponding-source link has to name the pinned release too'
    );
});

test('a pin without its own URLs is refused rather than resolved from latest', () => {
    assert.equal(pinnedSources({ key: 'yt-dlp' }), null);
    assert.throws(
        () => pinnedSources({ key: 'yt-dlp', pinnedVersion: '2026.07.04' }),
        /pinnedVersion 2026\.07\.04 needs pinnedDistributionUrl/
    );
    assert.throws(
        () => pinnedSources({
            key: 'yt-dlp',
            pinnedVersion: '2026.07.04',
            pinnedDistributionUrl: 'https://example.test/yt-dlp.exe'
        }),
        /pinnedChecksumUrl/
    );
});
