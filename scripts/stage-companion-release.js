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
const DEST = path.join(BUILD_DIR, 'AstraDownloader.exe');
const METADATA_DEST = path.join(BUILD_DIR, COMPANION_BUILD_METADATA_NAME);
const SIDECAR_DEST = path.join(BUILD_DIR, 'AstraDownloader.exe.sha256');
const MIN_BYTES = 1024;

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

function readValidatedSidecar(sidecarPath, companionExe) {
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
    const expected = sha256(companionExe);
    if (!match || match[1].toLowerCase() !== expected
        || path.basename(match[2].trim()) !== 'AstraDownloader.exe') {
        throw new Error('companion SHA-256 sidecar does not match the staged AstraDownloader.exe');
    }
    return expected;
}

function writeValidatedSidecar(sidecarPath, companionExe) {
    const digest = sha256(companionExe);
    fs.writeFileSync(sidecarPath, `${digest}  AstraDownloader.exe\n`, 'utf8');
    return readValidatedSidecar(sidecarPath, companionExe);
}

function stageCompanionRelease(
    sourcePath = DEFAULT_SOURCE,
    metadataPath = DEFAULT_METADATA_SOURCE,
    sidecarPath = `${sourcePath}.sha256`,
) {
    const resolvedSource = path.resolve(sourcePath);
    const resolvedSidecar = path.resolve(sidecarPath || DEFAULT_SIDECAR_SOURCE);
    assertBuildDirExists();
    const companionExe = readValidatedCompanionExe(resolvedSource);
    const metadata = readValidatedMetadata(path.resolve(metadataPath), companionExe);
    const companionDigest = readValidatedSidecar(resolvedSidecar, companionExe);
    fs.writeFileSync(DEST, companionExe);
    fs.writeFileSync(METADATA_DEST, JSON.stringify(metadata, null, 2) + '\n', 'utf8');
    writeValidatedSidecar(SIDECAR_DEST, companionExe);
    const stagedExe = fs.readFileSync(DEST);
    const stagedDigest = readValidatedSidecar(SIDECAR_DEST, stagedExe);
    if (stagedDigest !== companionDigest || stagedDigest !== sha256(stagedExe)) {
        throw new Error('staged companion EXE and SHA-256 sidecar do not match');
    }
    console.log(`Staged companion EXE: build/AstraDownloader.exe (${companionExe.length} bytes)`);
    console.log(`Staged companion inventory input: build/${COMPANION_BUILD_METADATA_NAME}`);
    console.log('Staged companion SHA-256 sidecar: build/AstraDownloader.exe.sha256');
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
    readValidatedSidecar,
    stageCompanionRelease
};
