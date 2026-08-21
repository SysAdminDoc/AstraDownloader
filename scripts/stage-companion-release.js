#!/usr/bin/env node
'use strict';

const fs = require('fs');
const crypto = require('crypto');
const path = require('path');
const zlib = require('zlib');
const {
    COMPANION_BUILD_METADATA_NAME,
    validateResolutionMetadata
} = require('./companion-license-inventory');
const {
    LOCK_NAME,
    SBOM_NAME,
    sbomDescribesArtifact
} = require('./write-release-provenance');

function readReleaseArtifact(name) {
    // No existence check: opening the file is the check, and a separate
    // exists-then-read pair is a race the staging path must not carry.
    try {
        return fs.readFileSync(path.join(BUILD_DIR, name), 'utf8');
    } catch (error) {
        if (error.code === 'ENOENT') {
            throw new Error(
                `missing build/${name}; run \`npm run release:provenance\` after building`
            );
        }
        throw error;
    }
}

function readReleaseArtifactJson(name) {
    return JSON.parse(readReleaseArtifact(name));
}

const REPO_ROOT = path.join(__dirname, '..');
const BUILD_DIR = path.join(REPO_ROOT, 'build');
const DEFAULT_SOURCE = path.join(REPO_ROOT, 'AstraDownloader.exe');
const DEFAULT_METADATA_SOURCE = path.join(REPO_ROOT, 'astra_downloader', 'build', COMPANION_BUILD_METADATA_NAME);
const DEFAULT_SIDECAR_SOURCE = `${DEFAULT_SOURCE}.sha256`;
const DEFAULT_ONEDIR_SOURCE = path.join(REPO_ROOT, 'AstraDownloader-onedir.zip');
const DEST = path.join(BUILD_DIR, 'AstraDownloader.exe');
const METADATA_DEST = path.join(BUILD_DIR, COMPANION_BUILD_METADATA_NAME);
const SIDECAR_DEST = path.join(BUILD_DIR, 'AstraDownloader.exe.sha256');
const ONEDIR_DEST = path.join(BUILD_DIR, 'AstraDownloader-onedir.zip');
const ONEDIR_SIDECAR_DEST = path.join(BUILD_DIR, 'AstraDownloader-onedir.zip.sha256');
const MIN_BYTES = 1024;
const ONEDIR_ENTRY = 'AstraDownloader/AstraDownloader.exe';
const ONEDIR_METADATA_ENTRY = `AstraDownloader/${COMPANION_BUILD_METADATA_NAME}`;

function openCompanionExe(filePath) {
    try {
        return fs.openSync(filePath, 'r');
    } catch (err) {
        if (err && err.code === 'ENOENT') {
            throw new Error(`missing companion EXE: ${filePath}`);
        }
        throw err;
    }
}

function readValidatedCompanionExe(filePath) {
    const fd = openCompanionExe(filePath);
    try {
        const stat = fs.fstatSync(fd);
        if (!stat.isFile()) {
            throw new Error(`companion path is not a file: ${filePath}`);
        }
        if (stat.size < MIN_BYTES) {
            throw new Error(`companion EXE is too small (${stat.size} bytes): ${filePath}`);
        }
        const header = Buffer.alloc(2);
        fs.readSync(fd, header, 0, 2, 0);
        if (header.toString('ascii') !== 'MZ') {
            throw new Error(`companion EXE does not have an MZ header: ${filePath}`);
        }

        const data = Buffer.alloc(stat.size);
        let offset = 0;
        while (offset < data.length) {
            const bytesRead = fs.readSync(fd, data, offset, data.length - offset, offset);
            if (bytesRead === 0) break;
            offset += bytesRead;
        }
        if (offset !== data.length) {
            throw new Error(`companion EXE changed while reading: ${filePath}`);
        }
        return data;
    } finally {
        fs.closeSync(fd);
    }
}

function readValidatedZipEntries(data) {
    const minimumEndRecord = 22;
    const searchStart = Math.max(0, data.length - minimumEndRecord - 0xffff);
    let endRecord = -1;
    for (let index = data.length - minimumEndRecord; index >= searchStart; index -= 1) {
        if (index + 4 <= data.length && data.readUInt32LE(index) === 0x06054b50) {
            endRecord = index;
            break;
        }
    }
    if (endRecord < 0) {
        throw new Error('one-folder archive has no ZIP end record');
    }
    if (
        data.readUInt16LE(endRecord + 4) !== 0
        || data.readUInt16LE(endRecord + 6) !== 0
        || data.readUInt16LE(endRecord + 8) !== data.readUInt16LE(endRecord + 10)
        || data.readUInt16LE(endRecord + 10) === 0xffff
    ) {
        throw new Error('one-folder archive uses unsupported ZIP64 or multi-disk metadata');
    }

    const entryCount = data.readUInt16LE(endRecord + 10);
    const centralDirectorySize = data.readUInt32LE(endRecord + 12);
    const centralDirectoryOffset = data.readUInt32LE(endRecord + 16);
    const centralDirectoryEnd = centralDirectoryOffset + centralDirectorySize;
    if (centralDirectoryEnd > endRecord || centralDirectoryOffset < 0) {
        throw new Error('one-folder archive has an invalid central directory');
    }

    const entries = new Map();
    let cursor = centralDirectoryOffset;
    for (let index = 0; index < entryCount; index += 1) {
        if (cursor + 46 > centralDirectoryEnd || data.readUInt32LE(cursor) !== 0x02014b50) {
            throw new Error('one-folder archive has an invalid central directory entry');
        }
        const flags = data.readUInt16LE(cursor + 8);
        const compressionMethod = data.readUInt16LE(cursor + 10);
        const compressedSize = data.readUInt32LE(cursor + 20);
        const uncompressedSize = data.readUInt32LE(cursor + 24);
        const nameLength = data.readUInt16LE(cursor + 28);
        const extraLength = data.readUInt16LE(cursor + 30);
        const commentLength = data.readUInt16LE(cursor + 32);
        const localHeaderOffset = data.readUInt32LE(cursor + 42);
        const entryEnd = cursor + 46 + nameLength + extraLength + commentLength;
        if (entryEnd > centralDirectoryEnd) {
            throw new Error('one-folder archive has a truncated central directory entry');
        }
        const name = data.toString('utf8', cursor + 46, cursor + 46 + nameLength)
            .replaceAll('\\', '/');
        const segments = name.split('/');
        if (
            !name
            || entries.has(name)
            || name.startsWith('/')
            || /^[A-Za-z]:/.test(name)
            || segments.includes('..')
            || (flags & 0x1) !== 0
        ) {
            throw new Error(`one-folder archive has an unsafe entry: ${name || '<empty>'}`);
        }
        entries.set(name, {
            name,
            compressionMethod,
            compressedSize,
            uncompressedSize,
            localHeaderOffset,
        });
        cursor = entryEnd;
    }
    if (cursor !== centralDirectoryEnd) {
        throw new Error('one-folder archive has trailing central directory data');
    }
    return entries;
}

function readValidatedZipEntry(data, entry) {
    const headerOffset = entry.localHeaderOffset;
    if (headerOffset + 30 > data.length || data.readUInt32LE(headerOffset) !== 0x04034b50) {
        throw new Error(`one-folder archive has an invalid local header: ${entry.name}`);
    }
    const nameLength = data.readUInt16LE(headerOffset + 26);
    const extraLength = data.readUInt16LE(headerOffset + 28);
    const localName = data.toString('utf8', headerOffset + 30, headerOffset + 30 + nameLength)
        .replaceAll('\\', '/');
    if (localName !== entry.name) {
        throw new Error(`one-folder archive local header does not match ${entry.name}`);
    }
    const dataStart = headerOffset + 30 + nameLength + extraLength;
    const dataEnd = dataStart + entry.compressedSize;
    if (dataStart < 0 || dataEnd > data.length) {
        throw new Error(`one-folder archive has truncated data: ${entry.name}`);
    }
    const compressed = data.subarray(dataStart, dataEnd);
    let unpacked;
    if (entry.compressionMethod === 0) {
        unpacked = compressed;
    } else if (entry.compressionMethod === 8) {
        unpacked = zlib.inflateRawSync(compressed);
    } else {
        throw new Error(`one-folder archive uses unsupported compression for ${entry.name}`);
    }
    if (unpacked.length !== entry.uncompressedSize) {
        throw new Error(`one-folder archive size mismatch for ${entry.name}`);
    }
    return unpacked;
}

function readEmbeddedBuildMetadata(archiveData) {
    let metadata;
    const entries = readValidatedZipEntries(archiveData);
    const entry = entries.get(ONEDIR_METADATA_ENTRY);
    if (!entry) {
        throw new Error(`one-folder archive is missing ${ONEDIR_METADATA_ENTRY}`);
    }
    try {
        metadata = JSON.parse(readValidatedZipEntry(archiveData, entry).toString('utf8'));
    } catch (err) {
        throw new Error(`invalid embedded companion build metadata: ${err.message}`);
    }
    return metadata;
}

function readValidatedOnedirArchive(filePath) {
    let fd;
    try {
        fd = fs.openSync(filePath, 'r');
    } catch (err) {
        if (err && err.code === 'ENOENT') {
            throw new Error(`missing one-folder archive: ${filePath}`);
        }
        throw err;
    }
    try {
        const stat = fs.fstatSync(fd);
        if (!stat.isFile()) {
            throw new Error(`one-folder archive path is not a file: ${filePath}`);
        }
        if (stat.size < MIN_BYTES) {
            throw new Error(`one-folder archive is too small (${stat.size} bytes): ${filePath}`);
        }
        const data = Buffer.alloc(stat.size);
        let offset = 0;
        while (offset < data.length) {
            const bytesRead = fs.readSync(fd, data, offset, data.length - offset, offset);
            if (bytesRead === 0) break;
            offset += bytesRead;
        }
        if (offset !== data.length) {
            throw new Error(`one-folder archive changed while reading: ${filePath}`);
        }

        const entries = readValidatedZipEntries(data);
        if (!entries.has(ONEDIR_ENTRY)) {
            throw new Error(`one-folder archive is missing ${ONEDIR_ENTRY}`);
        }
        return data;
    } finally {
        fs.closeSync(fd);
    }
}

const WINGET_MANIFEST_ROOT = path.join(
    REPO_ROOT, 'packaging', 'winget', 'manifests', 's', 'SysAdminDoc', 'AstraDownloader'
);

function wingetInstallerManifestPath(version) {
    return path.join(
        WINGET_MANIFEST_ROOT, version, 'SysAdminDoc.AstraDownloader.installer.yaml'
    );
}

function readWingetInstallerSha256(manifestText) {
    const match = String(manifestText).match(/^\s*InstallerSha256:\s*([0-9a-fA-F]{64})\s*$/m);
    return match ? match[1].toLowerCase() : null;
}

// The digest in the winget manifest is generated from the staged artifact,
// never written by hand: a hand-typed digest once shipped that matched no
// artifact in existence, and the version gate only checked that it was 64 hex
// digits. Staging writes it; the gate compares it (wingetDigestFailures).
function updateWingetManifestDigest(version, digest,
                                    manifestPath = wingetInstallerManifestPath(version)) {
    let text;
    try {
        text = fs.readFileSync(manifestPath, 'utf8');
    } catch (error) {
        throw new Error(
            `winget installer manifest for ${version} is missing: ${manifestPath}`
        );
    }
    if (!readWingetInstallerSha256(text)) {
        throw new Error(
            `winget installer manifest carries no InstallerSha256 field: ${manifestPath}`
        );
    }
    const updated = text.replace(
        /^(\s*InstallerSha256:\s*)[0-9a-fA-F]{64}\s*$/m,
        `$1${String(digest).toLowerCase()}`
    );
    fs.writeFileSync(manifestPath, updated, 'utf8');
    return manifestPath;
}

// Shared with check-versions.js so the gate and the writer agree by
// construction. `stagedMetadata` is build/companion-build-metadata.json; a
// missing or different-version build means there is nothing to compare, which
// is not a failure — the staging path above guarantees the digest is written
// whenever a release is actually staged.
function wingetDigestFailures(manifestText, version, stagedMetadata) {
    const declared = readWingetInstallerSha256(manifestText);
    if (!declared) {
        return ['winget installer manifest: InstallerSha256 must be a 64-digit hex digest'];
    }
    const metadata = stagedMetadata && typeof stagedMetadata === 'object' ? stagedMetadata : null;
    if (!metadata || metadata.version !== version) {
        return [];
    }
    const stagedDigest = metadata.artifact && metadata.artifact.sha256;
    if (typeof stagedDigest !== 'string' || !/^[0-9a-f]{64}$/i.test(stagedDigest)) {
        return [];
    }
    if (declared !== stagedDigest.toLowerCase()) {
        return [
            `winget InstallerSha256 (${declared.slice(0, 12)}…) does not match the staged ` +
            `AstraDownloader.exe (${stagedDigest.slice(0, 12).toLowerCase()}…) for v${version}; ` +
            'run `npm run release:stage` to regenerate it from the artifact'
        ];
    }
    return [];
}

function assertBuildDirExists() {
    let stat;
    try {
        stat = fs.statSync(BUILD_DIR);
    } catch (err) {
        if (err && err.code === 'ENOENT') {
            throw new Error('build/ does not exist. Run `py -3.13 astra_downloader/build.py` before staging the companion EXE.');
        }
        throw err;
    }
    if (!stat.isDirectory()) {
        throw new Error('build/ exists but is not a directory.');
    }
}

function sha256(data) {
    return crypto.createHash('sha256').update(data).digest('hex');
}

function readValidatedMetadata(metadataPath, companionExe) {
    let metadata;
    try {
        metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));
    } catch (err) {
        if (err && err.code === 'ENOENT') {
            throw new Error(`missing companion build metadata: ${metadataPath}; rebuild with astra_downloader/build.py`);
        }
        throw new Error(`invalid companion build metadata: ${err.message}`);
    }
    if (
        metadata.schemaVersion !== 2
        || !metadata.artifact
        || metadata.artifact.name !== 'AstraDownloader.exe'
        || metadata.artifact.size !== companionExe.length
        || metadata.artifact.sha256 !== sha256(companionExe)
        || !/^[0-9a-f]{64}$/i.test(String(metadata.buildId || ''))
        || !metadata.artifacts
        || !metadata.artifacts.onefile
        || metadata.artifacts.onefile.name !== metadata.artifact.name
        || metadata.artifacts.onefile.size !== metadata.artifact.size
        || metadata.artifacts.onefile.sha256 !== metadata.artifact.sha256
        || !metadata.artifacts.onedir
        || metadata.artifacts.onedir.name !== 'AstraDownloader-onedir.zip'
        || metadata.artifacts.onedir.version !== metadata.version
        || metadata.artifacts.onedir.buildId !== metadata.buildId
    ) {
        throw new Error('companion build metadata does not match the staged AstraDownloader.exe');
    }
    if (!metadata.python || !metadata.python.version || !Array.isArray(metadata.distributions)) {
        throw new Error('companion build metadata is missing Python or distribution inventory');
    }
    validateResolutionMetadata(metadata, REPO_ROOT);
    return metadata;
}

function readValidatedSidecar(sidecarPath, companionBytes, artifactName = 'AstraDownloader.exe') {
    let contents;
    try {
        contents = fs.readFileSync(sidecarPath, 'utf8').trim();
    } catch (err) {
        if (err && err.code === 'ENOENT') {
            throw new Error(`missing companion SHA-256 sidecar: ${sidecarPath}; rebuild with astra_downloader/build.py`);
        }
        throw new Error(`could not read companion SHA-256 sidecar: ${err.message}`);
    }
    const match = contents.match(/^([0-9a-f]{64})\s+\*?(.+)$/i);
    const expected = crypto.createHash('sha256').update(companionBytes).digest('hex');
    if (!match || match[1].toLowerCase() !== expected
        || path.basename(match[2].trim()) !== artifactName) {
        throw new Error(`companion SHA-256 sidecar does not match the staged ${artifactName}`);
    }
    return expected;
}

function validateSharedBuildMetadata(metadata, embeddedMetadata, onedirName) {
    if (
        embeddedMetadata.schemaVersion !== metadata.schemaVersion
        || embeddedMetadata.version !== metadata.version
        || embeddedMetadata.buildId !== metadata.buildId
        || !embeddedMetadata.artifacts
        || !embeddedMetadata.artifacts.onedir
        || embeddedMetadata.artifacts.onedir.name !== onedirName
        || embeddedMetadata.artifacts.onedir.version !== metadata.version
        || embeddedMetadata.artifacts.onedir.buildId !== metadata.buildId
    ) {
        throw new Error('one-file and one-folder companion metadata disagree on version or build');
    }
    return embeddedMetadata;
}

function writeValidatedSidecar(sidecarPath, companionBytes, artifactName = 'AstraDownloader.exe') {
    const digest = crypto.createHash('sha256').update(companionBytes).digest('hex');
    fs.writeFileSync(sidecarPath, `${digest}  ${artifactName}\n`, 'utf8');
    return readValidatedSidecar(sidecarPath, companionBytes, artifactName);
}

function stageCompanionRelease(
    sourcePath = DEFAULT_SOURCE,
    metadataPath = DEFAULT_METADATA_SOURCE,
    sidecarPath = `${sourcePath}.sha256`,
    onedirPath = DEFAULT_ONEDIR_SOURCE,
    onedirSidecarPath = `${onedirPath}.sha256`,
) {
    const resolvedSource = path.resolve(sourcePath);
    const resolvedSidecar = path.resolve(sidecarPath || DEFAULT_SIDECAR_SOURCE);
    const resolvedOnedir = path.resolve(onedirPath);
    const resolvedOnedirSidecar = path.resolve(onedirSidecarPath);
    assertBuildDirExists();
    const companionExe = readValidatedCompanionExe(resolvedSource);
    const metadata = readValidatedMetadata(path.resolve(metadataPath), companionExe);
    const companionDigest = readValidatedSidecar(resolvedSidecar, companionExe);
    const onedirArchive = readValidatedOnedirArchive(resolvedOnedir);
    const onedirName = path.basename(resolvedOnedir);
    const embeddedMetadata = readEmbeddedBuildMetadata(onedirArchive);
    validateSharedBuildMetadata(metadata, embeddedMetadata, onedirName);
    const onedirDigest = readValidatedSidecar(
        resolvedOnedirSidecar,
        onedirArchive,
        onedirName,
    );
    fs.writeFileSync(DEST, companionExe);
    fs.writeFileSync(METADATA_DEST, JSON.stringify(metadata, null, 2) + '\n', 'utf8');
    writeValidatedSidecar(SIDECAR_DEST, companionExe);
    fs.writeFileSync(ONEDIR_DEST, onedirArchive);
    writeValidatedSidecar(ONEDIR_SIDECAR_DEST, onedirArchive, onedirName);
    const stagedExe = fs.readFileSync(DEST);
    const stagedDigest = readValidatedSidecar(SIDECAR_DEST, stagedExe);
    const stagedOnedir = fs.readFileSync(ONEDIR_DEST);
    const stagedOnedirDigest = readValidatedSidecar(
        ONEDIR_SIDECAR_DEST,
        stagedOnedir,
        onedirName,
    );
    if (
        stagedDigest !== companionDigest
        || stagedDigest !== sha256(stagedExe)
        || stagedOnedirDigest !== onedirDigest
        || stagedOnedirDigest !== crypto.createHash('sha256').update(stagedOnedir).digest('hex')
    ) {
        throw new Error('staged companion artifacts and SHA-256 sidecars do not match');
    }
    // Provenance must describe THIS binary. A release that ships last build's
    // SBOM is worse than one that ships none: it reads as a verified inventory
    // while naming components that were never in the artifact.
    const stagedArtifactSha256 = crypto.createHash('sha256').update(companionExe).digest('hex');
    if (!sbomDescribesArtifact(readReleaseArtifactJson(SBOM_NAME), stagedArtifactSha256)) {
        throw new Error(
            `build/${SBOM_NAME} does not describe the staged AstraDownloader.exe; ` +
            'regenerate it with `npm run release:provenance`'
        );
    }
    // Read rather than probed: the lock must exist and be non-empty, and an
    // existence check would only tell us it was there a moment ago.
    if (!readReleaseArtifact(LOCK_NAME).trim()) {
        throw new Error(`build/${LOCK_NAME} is empty; regenerate it with \`npm run release:provenance\``);
    }

    const wingetManifest = updateWingetManifestDigest(metadata.version, stagedArtifactSha256);
    console.log(`Staged companion EXE: build/AstraDownloader.exe (${companionExe.length} bytes)`);
    console.log(`Updated winget InstallerSha256: ${path.relative(REPO_ROOT, wingetManifest)}`);
    console.log(`Staged release SBOM: build/${SBOM_NAME}`);
    console.log(`Staged release lock: build/${LOCK_NAME}`);
    console.log(`Staged companion inventory input: build/${COMPANION_BUILD_METADATA_NAME}`);
    console.log('Staged companion SHA-256 sidecar: build/AstraDownloader.exe.sha256');
    console.log(`Staged one-folder archive: build/${onedirName} (${onedirArchive.length} bytes)`);
    console.log(`Staged one-folder SHA-256 sidecar: build/${onedirName}.sha256`);
}

if (require.main === module) {
    try {
        stageCompanionRelease(process.argv[2] || DEFAULT_SOURCE, process.argv[3] || DEFAULT_METADATA_SOURCE);
    } catch (err) {
        console.error('[stage-companion-release] ' + err.message);
        process.exit(1);
    }
}

module.exports = {
    readValidatedMetadata,
    readValidatedOnedirArchive,
    readEmbeddedBuildMetadata,
    readValidatedSidecar,
    validateSharedBuildMetadata,
    stageCompanionRelease,
    wingetInstallerManifestPath,
    readWingetInstallerSha256,
    updateWingetManifestDigest,
    wingetDigestFailures
};
