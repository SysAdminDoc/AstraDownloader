'use strict';

// These tests moved here from the Astra Deck repository when Astra Downloader
// became its own product: they exercise scripts/companion-license-inventory.js
// and scripts/stage-companion-release.js, which now live in this repository
// and describe this repository's release artifact.

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const {
    PROPERTY,
    buildCompanionInventory,
    inspectCompanionInventory
} = require('../scripts/companion-license-inventory');
const { checkCompanionInventory } = require('../scripts/check-companion-inventory');

function sha256(filePath) {
    return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

function storedZip(entries) {
    const locals = [];
    const centrals = [];
    let offset = 0;
    for (const [name, content] of entries) {
        const nameBytes = Buffer.from(name, 'utf8');
        const data = Buffer.from(content);
        const local = Buffer.alloc(30 + nameBytes.length + data.length);
        local.writeUInt32LE(0x04034b50, 0);
        local.writeUInt16LE(20, 4);
        local.writeUInt16LE(0, 6);
        local.writeUInt16LE(0, 8);
        local.writeUInt32LE(data.length, 18);
        local.writeUInt32LE(data.length, 22);
        local.writeUInt16LE(nameBytes.length, 26);
        nameBytes.copy(local, 30);
        data.copy(local, 30 + nameBytes.length);
        locals.push(local);

        const central = Buffer.alloc(46 + nameBytes.length);
        central.writeUInt32LE(0x02014b50, 0);
        central.writeUInt16LE(20, 4);
        central.writeUInt16LE(20, 6);
        central.writeUInt16LE(0, 8);
        central.writeUInt16LE(0, 10);
        central.writeUInt32LE(data.length, 20);
        central.writeUInt32LE(data.length, 24);
        central.writeUInt16LE(nameBytes.length, 28);
        central.writeUInt32LE(offset, 42);
        nameBytes.copy(central, 46);
        centrals.push(central);
        offset += local.length;
    }
    const centralDirectory = Buffer.concat(centrals);
    const end = Buffer.alloc(22);
    end.writeUInt32LE(0x06054b50, 0);
    end.writeUInt16LE(entries.length, 8);
    end.writeUInt16LE(entries.length, 10);
    end.writeUInt32LE(centralDirectory.length, 12);
    end.writeUInt32LE(offset, 16);
    return Buffer.concat([...locals, centralDirectory, end]);
}

function writeCompanionInventoryFixture(root, buildDir) {
    const exe = Buffer.concat([Buffer.from('MZ'), Buffer.alloc(2048, 9)]);
    const exePath = path.join(buildDir, 'AstraDownloader.exe');
    fs.writeFileSync(exePath, exe);
    fs.mkdirSync(path.join(root, 'astra_downloader'), { recursive: true });
    fs.copyFileSync(
        path.join(__dirname, '..', 'astra_downloader', 'license-policy.json'),
        path.join(root, 'astra_downloader', 'license-policy.json')
    );
    fs.copyFileSync(
        path.join(__dirname, '..', 'astra_downloader', 'constraints-release.txt'),
        path.join(root, 'astra_downloader', 'constraints-release.txt')
    );
    const constraintsSha256 = sha256(path.join(root, 'astra_downloader', 'constraints-release.txt'));
    const licenseFile = [{ path: 'package.dist-info/LICENSE', sha256: 'b'.repeat(64) }];
    const resolvedPackages = [
        { name: 'PyInstaller', version: '6.21.0', scope: 'build', license: 'MIT', dependsOn: [] },
        { name: 'PyQt6', version: '6.11.0', scope: 'embedded', license: 'GPL-3.0-only', dependsOn: ['pyqt6-qt6'] },
        { name: 'PyQt6-Qt6', version: '6.11.1', scope: 'embedded', license: 'LGPL-3.0-only', dependsOn: [] },
        { name: 'requests', version: '2.34.2', scope: 'validation', license: 'Apache-2.0', dependsOn: [] }
    ];
    const metadata = {
        schemaVersion: 2,
        version: '1.5.1',
        artifact: {
            name: 'AstraDownloader.exe',
            size: exe.length,
            sha256: sha256(exePath)
        },
        python: {
            implementation: 'CPython',
            version: '3.12.10',
            license: 'Python-2.0',
            sourceUrl: 'https://www.python.org/'
        },
        resolution: {
            schemaVersion: 1,
            constraintsPath: 'astra_downloader/constraints-release.txt',
            constraintsSha256,
            supportedPythonMinors: ['3.11', '3.12'],
            direct: ['pyinstaller', 'pyqt6', 'requests'],
            packages: resolvedPackages
        },
        distributions: [
            {
                name: 'PyInstaller',
                version: '6.21.0',
                scope: 'build',
                license: 'GPLv2-or-later with special exception',
                sourceUrl: 'https://pyinstaller.org/',
                recordSha256: '1'.repeat(64),
                licenseFiles: licenseFile
            },
            {
                name: 'PyQt6',
                version: '6.11.0',
                scope: 'embedded',
                license: 'GPL-3.0-only',
                sourceUrl: 'https://pypi.org/project/PyQt6/',
                recordSha256: '2'.repeat(64),
                licenseFiles: licenseFile
            },
            {
                name: 'PyQt6-Qt6',
                version: '6.11.1',
                scope: 'embedded',
                license: 'LGPL-3.0-only',
                sourceUrl: 'https://pypi.org/project/PyQt6-Qt6/',
                recordSha256: '3'.repeat(64),
                licenseFiles: licenseFile
            }
        ]
    };
    fs.writeFileSync(
        path.join(buildDir, 'companion-build-metadata.json'),
        JSON.stringify(metadata, null, 2) + '\n'
    );
    return {
        artifactSha256: metadata.artifact.sha256,
        inventory: buildCompanionInventory(root, buildDir)
    };
}

// In Astra Deck this reused the extension release fixture for a root and a
// build directory. Here the inventory is the whole subject, so a bare temp
// tree is all it needs.
function writeEmptyBuildTree() {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-companion-license-'));
    const buildDir = path.join(root, 'build');
    fs.mkdirSync(buildDir, { recursive: true });
    return { root, buildDir };
}

test('companion SBOM inventory carries the reviewed Python resolution graph', () => {
    const { root, buildDir } = writeEmptyBuildTree();
    const { inventory } = writeCompanionInventoryFixture(root, buildDir);
    const requests = inventory.components.find((component) => component['bom-ref'] === 'pkg:pypi/requests@2.34.2');
    const pyqt = inventory.dependencies.find((entry) => entry.ref === 'pkg:pypi/pyqt6@6.11.0');

    assert.ok(requests, 'a constraints-only package must still appear in the release SBOM');
    assert.equal(requests.scope, 'excluded', 'validation-only packages must not be represented as shipped');
    assert.equal(
        requests.properties.find((item) => item.name === PROPERTY.resolutionGraph).value,
        'true'
    );
    assert.deepEqual(pyqt.dependsOn, ['pkg:pypi/pyqt6-qt6@6.11.1']);
});

test('companion license inspection covers release components without the auxiliary tag', () => {
    const { root, buildDir } = writeEmptyBuildTree();
    const { artifactSha256, inventory } = writeCompanionInventoryFixture(root, buildDir);
    const pyqt = inventory.components.find((component) => component.name === 'PyQt6');
    pyqt.properties = pyqt.properties.filter((entry) => entry.name !== PROPERTY.inventory);
    const inspection = inspectCompanionInventory({ components: inventory.components }, artifactSha256);
    assert.ok(
        inspection.components.some((component) => component.name === 'PyQt6'),
        'a required component must not disappear when the auxiliary tag is absent'
    );
});

test('companion SBOM inventory fails when the staged executable is missing', () => {
    const { root, buildDir } = writeEmptyBuildTree();
    assert.throws(
        () => buildCompanionInventory(root, buildDir),
        /missing staged companion artifact/
    );
});

test('companion SBOM inventory links exact embedded versions to the staged artifact and names unresolved obligations', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-companion-license-'));
    const buildDir = path.join(root, 'build');
    fs.mkdirSync(buildDir, { recursive: true });
    const { artifactSha256, inventory } = writeCompanionInventoryFixture(root, buildDir);
    const sbom = { components: inventory.components };
    const inspection = inspectCompanionInventory(sbom, artifactSha256);

    assert.ok(inventory.components.some((component) => component.name === 'CPython' && component.version === '3.12.10'));
    assert.ok(inventory.components.some((component) => component.name === 'PyQt6' && component.version === '6.11.0'));
    assert.equal(
        inventory.components.every((component) => (
            component.properties.find((entry) => entry.name === PROPERTY.artifactSha256).value === artifactSha256
        )),
        true
    );
    assert.ok(inspection.issues.some((issue) => /pyqt6: decision=unresolved/i.test(issue)));
    assert.ok(inspection.issues.some((issue) => /ffmpeg: exact version is unresolved/i.test(issue)));
    assert.ok(inspection.issues.some((issue) => /yt-dlp: exact download SHA-256 is unresolved/i.test(issue)));
});

test('companion license inspection fails closed on disallowed decisions and clears only after exact approvals', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-companion-license-'));
    const buildDir = path.join(root, 'build');
    fs.mkdirSync(buildDir, { recursive: true });
    const { artifactSha256, inventory } = writeCompanionInventoryFixture(root, buildDir);
    const sbom = { components: inventory.components };

    for (const component of sbom.components) {
        const decision = component.properties.find((entry) => entry.name === PROPERTY.decision);
        if (decision) decision.value = 'approved';
        const evidence = component.properties.find((entry) => entry.name === PROPERTY.evidence);
        if (evidence && !evidence.value) evidence.value = 'reviewed fixture evidence';
        if (/^(?:unknown|unresolved|latest|dynamic)$/i.test(component.version)) component.version = '1.2.3';
        const downloadHash = component.properties.find((entry) => entry.name === PROPERTY.downloadSha256);
        if (downloadHash) downloadHash.value = 'a'.repeat(64);
        for (const propertyName of [PROPERTY.distributionUrl, PROPERTY.checksumUrl, PROPERTY.sourceUrl]) {
            const url = component.properties.find((entry) => entry.name === propertyName);
            if (url && /latest/i.test(url.value)) url.value = 'https://example.test/releases/v1.2.3/artifact';
        }
    }
    assert.deepEqual(inspectCompanionInventory(sbom, artifactSha256).issues, []);

    const pyqt = sbom.components.find((component) => component.name === 'PyQt6');
    pyqt.properties.find((entry) => entry.name === PROPERTY.decision).value = 'disallowed';
    assert.ok(inspectCompanionInventory(sbom, artifactSha256).issues.some(
        (issue) => /pyqt6: decision=disallowed/i.test(issue)
    ));
});

test('the companion gate rejects a planted unresolved component', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-companion-license-'));
    const buildDir = path.join(root, 'build');
    fs.mkdirSync(buildDir, { recursive: true });
    const { artifactSha256, inventory } = writeCompanionInventoryFixture(root, buildDir);
    const sbom = { components: inventory.components, dependencies: inventory.dependencies };
    for (const component of sbom.components) {
        const decision = component.properties.find((entry) => entry.name === PROPERTY.decision);
        if (decision) decision.value = 'approved';
        const evidence = component.properties.find((entry) => entry.name === PROPERTY.evidence);
        if (evidence && !evidence.value) evidence.value = 'reviewed fixture evidence';
        if (/^(?:unknown|unresolved|latest|dynamic)$/i.test(component.version)) component.version = '1.2.3';
        const downloadHash = component.properties.find((entry) => entry.name === PROPERTY.downloadSha256);
        if (downloadHash) downloadHash.value = 'a'.repeat(64);
        for (const propertyName of [PROPERTY.distributionUrl, PROPERTY.checksumUrl, PROPERTY.sourceUrl]) {
            const url = component.properties.find((entry) => entry.name === propertyName);
            if (url && /latest/i.test(url.value)) url.value = 'https://example.test/releases/v1.2.3/artifact';
        }
    }
    assert.doesNotThrow(() => checkCompanionInventory(sbom, artifactSha256));
    const pyqt = sbom.components.find((component) => component.name === 'PyQt6');
    pyqt.properties.find((entry) => entry.name === PROPERTY.decision).value = 'unresolved';
    assert.throws(
        () => checkCompanionInventory(sbom, artifactSha256),
        /companion license inspection failed.*pyqt6: decision=unresolved/is
    );
});

test('companion staging metadata is accepted only for the exact EXE bytes', () => {
    const { readValidatedMetadata } = require('../scripts/stage-companion-release');
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-companion-stage-'));
    const metadataPath = path.join(root, 'companion-build-metadata.json');
    const exe = Buffer.concat([Buffer.from('MZ'), Buffer.alloc(2048, 4)]);
    const metadata = {
        schemaVersion: 2,
        artifact: { name: 'AstraDownloader.exe', size: exe.length, sha256: crypto.createHash('sha256').update(exe).digest('hex') },
        python: { version: '3.12.10' },
        resolution: {
            schemaVersion: 1,
            constraintsPath: 'astra_downloader/constraints-release.txt',
            constraintsSha256: sha256(path.join(__dirname, '..', 'astra_downloader', 'constraints-release.txt')),
            supportedPythonMinors: ['3.11', '3.12'],
            direct: ['pyinstaller'],
            packages: [{ name: 'PyInstaller', version: '6.21.0', scope: 'build', dependsOn: [] }]
        },
        distributions: []
    };
    fs.writeFileSync(metadataPath, JSON.stringify(metadata));

    assert.equal(readValidatedMetadata(metadataPath, exe).artifact.sha256, metadata.artifact.sha256);
    fs.writeFileSync(metadataPath, JSON.stringify({ ...metadata, resolution: undefined }));
    assert.throws(
        () => readValidatedMetadata(metadataPath, exe),
        /reviewed release resolution graph/
    );
    fs.writeFileSync(metadataPath, JSON.stringify(metadata));
    assert.throws(
        () => readValidatedMetadata(metadataPath, Buffer.concat([Buffer.from('MZ'), Buffer.alloc(2048, 5)])),
        /does not match/
    );
});

test('companion staging validates the SHA-256 sidecar pair', () => {
    const { readValidatedSidecar } = require('../scripts/stage-companion-release');
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-companion-sidecar-'));
    const exe = Buffer.concat([Buffer.from('MZ'), Buffer.alloc(2048, 7)]);
    const digest = crypto.createHash('sha256').update(exe).digest('hex');
    const sidecar = path.join(root, 'AstraDownloader.exe.sha256');

    fs.writeFileSync(sidecar, `${digest}  AstraDownloader.exe\n`);
    assert.equal(readValidatedSidecar(sidecar, exe), digest);

    fs.writeFileSync(sidecar, `${'a'.repeat(64)}  AstraDownloader.exe\n`);
    assert.throws(
        () => readValidatedSidecar(sidecar, exe),
        /sidecar does not match/
    );
});

test('one-folder staging validates the ZIP contents and sidecar pair', () => {
    const { readValidatedOnedirArchive, readValidatedSidecar } = require('../scripts/stage-companion-release');
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-companion-onedir-'));
    const archivePath = path.join(root, 'AstraDownloader-onedir.zip');
    const archive = storedZip([
        ['AstraDownloader/AstraDownloader.exe', Buffer.concat([Buffer.from('MZ'), Buffer.alloc(2048, 8)])],
        ['AstraDownloader/translations/astra_downloader_en.qm', Buffer.from('compiled')],
    ]);
    fs.writeFileSync(archivePath, archive);
    const sidecarPath = `${archivePath}.sha256`;
    const digest = crypto.createHash('sha256').update(archive).digest('hex');
    fs.writeFileSync(sidecarPath, `${digest}  AstraDownloader-onedir.zip\n`);

    assert.deepEqual(readValidatedOnedirArchive(archivePath), archive);
    assert.equal(readValidatedSidecar(sidecarPath, archive, 'AstraDownloader-onedir.zip'), digest);

    fs.writeFileSync(sidecarPath, `${digest}  AstraDownloader.exe\n`);
    assert.throws(
        () => readValidatedSidecar(sidecarPath, archive, 'AstraDownloader-onedir.zip'),
        /sidecar does not match/
    );
});


test('companion staging validates the opened descriptor rather than a path', () => {
    // Moved from the Astra Deck hardening suite with the script it pins.
    // Each assertion closes a TOCTOU gap: validating metadata against a path
    // that is re-opened later lets the bytes change between check and stage.
    const stageScriptSource = fs.readFileSync(
        path.join(__dirname, '..', 'scripts', 'stage-companion-release.js'), 'utf8'
    );
    assert.match(stageScriptSource, /MZ/,
        'companion staging must reject files without a Windows EXE header');
    assert.match(stageScriptSource, /build\/AstraDownloader\.exe/,
        'companion staging must stage the EXE into build/ for release manifest inclusion');
    assert.match(stageScriptSource, /AstraDownloader\.exe\.sha256/,
        'companion staging must carry the checksum sidecar beside the EXE');
    assert.match(stageScriptSource, /AstraDownloader-onedir\.zip/,
        'companion staging must carry the one-folder archive');
    assert.match(stageScriptSource, /readValidatedOnedirArchive/,
        'companion staging must validate the one-folder archive contents');
    assert.doesNotMatch(stageScriptSource, /release:manifest/,
        'companion staging must not refer to a nonexistent release:manifest script');
    assert.doesNotMatch(stageScriptSource, /build:userscript/,
        'companion staging must name the Python build command that actually exists');
    assert.match(stageScriptSource, /companion-build-metadata\.json|COMPANION_BUILD_METADATA_NAME/,
        'companion staging must carry artifact-linked Python distribution metadata into the SBOM pipeline');
    assert.match(stageScriptSource, /metadata\.artifact\.sha256 !== sha256\(companionExe\)/,
        'companion staging must reject metadata for a different binary');
    assert.match(stageScriptSource, /fs\.fstatSync\(fd\)/,
        'companion staging must validate metadata from the opened descriptor');
    assert.doesNotMatch(stageScriptSource, /fs\.existsSync/,
        'companion staging must avoid existence-check races');
    assert.doesNotMatch(stageScriptSource, /fs\.copyFileSync/,
        'companion staging must not copy a path after validating a different opened handle');
});
