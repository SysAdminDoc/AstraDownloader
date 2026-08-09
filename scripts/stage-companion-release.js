#!/usr/bin/env node
'use strict';

const fs = require('fs');
const crypto = require('crypto');
const path = require('path');
const {
    COMPANION_BUILD_METADATA_NAME,
    validateResolutionMetadata
} = require('./companion-license-inventory');

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

        const minimumEndRecord = 22;
        const searchStart = Math.max(0, data.length - minimumEndRecord - 0xffff);
        let endRecord = -1;
        for (let index = data.length - minimumEndRecord; index >= searchStart; index -= 1) {
            if (data.readUInt32LE(index) === 0x06054b50) {
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

        const entries = new Set();
        let cursor = centralDirectoryOffset;
        for (let index = 0; index < entryCount; index += 1) {
            if (cursor + 46 > centralDirectoryEnd || data.readUInt32LE(cursor) !== 0x02014b50) {
                throw new Error('one-folder archive has an invalid central directory entry');
            }
            const flags = data.readUInt16LE(cursor + 8);
            const nameLength = data.readUInt16LE(cursor + 28);
            const extraLength = data.readUInt16LE(cursor + 30);
            const commentLength = data.readUInt16LE(cursor + 32);
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
            entries.add(name);
            cursor = entryEnd;
        }
        if (cursor !== centralDirectoryEnd || !entries.has(ONEDIR_ENTRY)) {
            throw new Error(`one-folder archive is missing ${ONEDIR_ENTRY}`);
        }
        return data;
    } finally {
        fs.closeSync(fd);
    }
}

function assertBuildDirExists() {
    let stat;
    try {
        stat = fs.statSync(BUILD_DIR);
    } catch (err) {
        if (err && err.code === 'ENOENT') {
            throw new Error('build/ does not exist. Run `py -3.12 astra_downloader/build.py` before staging the companion EXE.');
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
    console.log(`Staged companion EXE: build/AstraDownloader.exe (${companionExe.length} bytes)`);
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
    readValidatedSidecar,
    stageCompanionRelease
};
