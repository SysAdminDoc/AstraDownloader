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
    sbomDescribesArtifact,
    writeReleaseProvenance
} = require('./write-release-provenance');
const { resolveRuntimeHelpers } = require('./resolve-runtime-helpers');
const { checkCompanionInventory } = require('./check-companion-inventory');

function readReleaseArtifact(name, releaseDir = BUILD_DIR) {
    // No existence check: opening the file is the check, and a separate
    // exists-then-read pair is a race the staging path must not carry.
    try {
        return fs.readFileSync(path.join(releaseDir, name), 'utf8');
    } catch (error) {
        if (error.code === 'ENOENT') {
            throw new Error(
                `missing release artifact ${path.join(releaseDir, name)}`
            );
        }
        throw error;
    }
}

function readReleaseArtifactJson(name, releaseDir = BUILD_DIR) {
    return JSON.parse(readReleaseArtifact(name, releaseDir));
}

const REPO_ROOT = path.join(__dirname, '..');
const BUILD_DIR = path.join(REPO_ROOT, 'build');
const DEFAULT_SOURCE = path.join(REPO_ROOT, 'AstraDownloader.exe');
const DEFAULT_METADATA_SOURCE = path.join(REPO_ROOT, 'astra_downloader', 'build', COMPANION_BUILD_METADATA_NAME);
const DEFAULT_SIDECAR_SOURCE = `${DEFAULT_SOURCE}.sha256`;
const DEFAULT_ONEDIR_SOURCE = path.join(REPO_ROOT, 'AstraDownloader-onedir.zip');
const MIN_BYTES = 1024;
const ONEDIR_ENTRY = 'AstraDownloader/AstraDownloader.exe';
const ONEDIR_METADATA_ENTRY = `AstraDownloader/${COMPANION_BUILD_METADATA_NAME}`;
const RELEASE_FILE_NAMES = Object.freeze([
    'AstraDownloader.exe',
    COMPANION_BUILD_METADATA_NAME,
    'AstraDownloader.exe.sha256',
    'AstraDownloader-onedir.zip',
    'AstraDownloader-onedir.zip.sha256',
    SBOM_NAME,
    LOCK_NAME,
]);

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

function assertBuildDirExists(buildDir = BUILD_DIR) {
    let stat;
    try {
        stat = fs.statSync(buildDir);
    } catch (err) {
        if (err && err.code === 'ENOENT') {
            throw new Error(`${buildDir} does not exist. Build the companion before staging the release.`);
        }
        throw err;
    }
    if (!stat.isDirectory()) {
        throw new Error(`${buildDir} is not a directory.`);
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

function writeCandidateArtifacts(candidateDir, options = {}) {
    const sourcePath = options.sourcePath || DEFAULT_SOURCE;
    const metadataPath = options.metadataPath || DEFAULT_METADATA_SOURCE;
    const sidecarPath = options.sidecarPath || `${sourcePath}.sha256`;
    const onedirPath = options.onedirPath || DEFAULT_ONEDIR_SOURCE;
    const onedirSidecarPath = options.onedirSidecarPath || `${onedirPath}.sha256`;
    const resolvedSource = path.resolve(sourcePath);
    const resolvedSidecar = path.resolve(sidecarPath || DEFAULT_SIDECAR_SOURCE);
    const resolvedOnedir = path.resolve(onedirPath);
    const resolvedOnedirSidecar = path.resolve(onedirSidecarPath);
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
    fs.writeFileSync(path.join(candidateDir, 'AstraDownloader.exe'), companionExe);
    fs.writeFileSync(
        path.join(candidateDir, COMPANION_BUILD_METADATA_NAME),
        `${JSON.stringify(metadata, null, 2)}\n`,
        'utf8',
    );
    const stagedDigest = writeValidatedSidecar(
        path.join(candidateDir, 'AstraDownloader.exe.sha256'),
        companionExe,
    );
    fs.writeFileSync(path.join(candidateDir, 'AstraDownloader-onedir.zip'), onedirArchive);
    const stagedOnedirDigest = writeValidatedSidecar(
        path.join(candidateDir, 'AstraDownloader-onedir.zip.sha256'),
        onedirArchive,
        onedirName,
    );
    if (
        stagedDigest !== companionDigest
        || stagedDigest !== sha256(companionExe)
        || stagedOnedirDigest !== onedirDigest
        || stagedOnedirDigest !== sha256(onedirArchive)
    ) {
        throw new Error('candidate companion artifacts and SHA-256 sidecars do not match');
    }
    return { companionDigest, metadata, onedirDigest };
}

function validateReleaseCandidate(candidateDir) {
    const entries = fs.readdirSync(candidateDir, { withFileTypes: true });
    const actualNames = entries.map((entry) => entry.name).sort();
    const expectedNames = [...RELEASE_FILE_NAMES].sort();
    if (
        entries.some((entry) => !entry.isFile())
        || actualNames.length !== expectedNames.length
        || actualNames.some((name, index) => name !== expectedNames[index])
    ) {
        throw new Error(
            `release candidate must contain exactly: ${expectedNames.join(', ')}`
        );
    }

    const companionExe = readValidatedCompanionExe(
        path.join(candidateDir, 'AstraDownloader.exe')
    );
    const metadata = readValidatedMetadata(
        path.join(candidateDir, COMPANION_BUILD_METADATA_NAME),
        companionExe,
    );
    const companionDigest = readValidatedSidecar(
        path.join(candidateDir, 'AstraDownloader.exe.sha256'),
        companionExe,
    );
    const onedirName = 'AstraDownloader-onedir.zip';
    const onedirArchive = readValidatedOnedirArchive(path.join(candidateDir, onedirName));
    const embeddedMetadata = readEmbeddedBuildMetadata(onedirArchive);
    validateSharedBuildMetadata(metadata, embeddedMetadata, onedirName);
    readValidatedSidecar(
        path.join(candidateDir, `${onedirName}.sha256`),
        onedirArchive,
        onedirName,
    );

    const sbom = readReleaseArtifactJson(SBOM_NAME, candidateDir);
    if (!sbomDescribesArtifact(sbom, companionDigest)) {
        throw new Error(
            `${SBOM_NAME} does not describe the candidate AstraDownloader.exe`
        );
    }
    if (!readReleaseArtifact(LOCK_NAME, candidateDir).trim()) {
        throw new Error(`${LOCK_NAME} is empty`);
    }
    checkCompanionInventory(sbom, companionDigest);
    return { companionDigest, metadata, onedirBytes: onedirArchive.length };
}

function safeRemoveTemporaryDirectory(directory, parentDirectory, prefix) {
    const resolvedDirectory = path.resolve(directory);
    const resolvedParent = path.resolve(parentDirectory);
    if (
        path.dirname(resolvedDirectory) !== resolvedParent
        || !path.basename(resolvedDirectory).startsWith(prefix)
    ) {
        throw new Error(`refusing to remove unsafe temporary path: ${resolvedDirectory}`);
    }
    fs.rmSync(resolvedDirectory, { recursive: true, force: true });
}

function publishReleaseCandidate(
    candidateDir,
    buildDir = BUILD_DIR,
    names = RELEASE_FILE_NAMES,
) {
    assertBuildDirExists(buildDir);
    const parentDirectory = path.dirname(path.resolve(buildDir));
    const backupPrefix = '.astra-release-backup-';
    const backupDir = fs.mkdtempSync(path.join(parentDirectory, backupPrefix));
    const movedOriginals = [];
    const movedCandidates = [];

    try {
        for (const name of names) {
            try {
                fs.renameSync(path.join(buildDir, name), path.join(backupDir, name));
                movedOriginals.push(name);
            } catch (error) {
                if (!error || error.code !== 'ENOENT') throw error;
            }
        }
        for (const name of names) {
            fs.renameSync(path.join(candidateDir, name), path.join(buildDir, name));
            movedCandidates.push(name);
        }
    } catch (publicationError) {
        const rollbackErrors = [];
        for (const name of [...movedCandidates].reverse()) {
            try {
                fs.renameSync(path.join(buildDir, name), path.join(candidateDir, name));
            } catch (error) {
                rollbackErrors.push(error);
            }
        }
        for (const name of [...movedOriginals].reverse()) {
            try {
                fs.renameSync(path.join(backupDir, name), path.join(buildDir, name));
            } catch (error) {
                rollbackErrors.push(error);
            }
        }
        if (rollbackErrors.length) {
            throw new AggregateError(
                [publicationError, ...rollbackErrors],
                `release publication failed and rollback is incomplete; recovery files remain in ${backupDir}`,
            );
        }
        safeRemoveTemporaryDirectory(backupDir, parentDirectory, backupPrefix);
        throw publicationError;
    }

    safeRemoveTemporaryDirectory(backupDir, parentDirectory, backupPrefix);
}

async function runReleaseTransaction(options = {}) {
    const buildDir = path.resolve(options.buildDir || BUILD_DIR);
    const resolveHelpers = options.resolveHelpers || resolveRuntimeHelpers;
    const writeCandidate = options.writeCandidate || (
        (candidateDir) => writeCandidateArtifacts(candidateDir, options.artifacts)
    );
    const writeProvenance = options.writeProvenance || writeReleaseProvenance;
    const validateCandidate = options.validateCandidate || validateReleaseCandidate;
    const publishCandidate = options.publishCandidate || publishReleaseCandidate;

    assertBuildDirExists(buildDir);
    await resolveHelpers();

    const parentDirectory = path.dirname(buildDir);
    const candidatePrefix = '.astra-release-candidate-';
    const candidateDir = fs.mkdtempSync(path.join(parentDirectory, candidatePrefix));
    try {
        await writeCandidate(candidateDir);
        await writeProvenance(candidateDir);
        const validation = await validateCandidate(candidateDir);
        await publishCandidate(candidateDir, buildDir, RELEASE_FILE_NAMES);
        return validation;
    } finally {
        safeRemoveTemporaryDirectory(candidateDir, parentDirectory, candidatePrefix);
    }
}

async function stageCompanionRelease(
    sourcePath = DEFAULT_SOURCE,
    metadataPath = DEFAULT_METADATA_SOURCE,
    sidecarPath = `${sourcePath}.sha256`,
    onedirPath = DEFAULT_ONEDIR_SOURCE,
    onedirSidecarPath = `${onedirPath}.sha256`,
) {
    const validation = await runReleaseTransaction({
        buildDir: BUILD_DIR,
        artifacts: {
            sourcePath,
            metadataPath,
            sidecarPath,
            onedirPath,
            onedirSidecarPath,
        },
    });

    console.log(`Staged companion EXE: build/AstraDownloader.exe`);
    console.log(`Staged release SBOM: build/${SBOM_NAME}`);
    console.log(`Staged release lock: build/${LOCK_NAME}`);
    console.log(`Staged companion inventory input: build/${COMPANION_BUILD_METADATA_NAME}`);
    console.log('Staged companion SHA-256 sidecar: build/AstraDownloader.exe.sha256');
    console.log(`Staged one-folder archive: build/AstraDownloader-onedir.zip (${validation.onedirBytes} bytes)`);
    console.log('Staged one-folder SHA-256 sidecar: build/AstraDownloader-onedir.zip.sha256');
    return validation;
}

if (require.main === module) {
    stageCompanionRelease(
        process.argv[2] || DEFAULT_SOURCE,
        process.argv[3] || DEFAULT_METADATA_SOURCE,
    ).catch((err) => {
        console.error('[stage-companion-release] ' + err.message);
        process.exitCode = 1;
    });
}

module.exports = {
    RELEASE_FILE_NAMES,
    publishReleaseCandidate,
    readValidatedMetadata,
    readValidatedOnedirArchive,
    readEmbeddedBuildMetadata,
    readValidatedSidecar,
    runReleaseTransaction,
    validateReleaseCandidate,
    validateSharedBuildMetadata,
    writeCandidateArtifacts,
    stageCompanionRelease,
};
