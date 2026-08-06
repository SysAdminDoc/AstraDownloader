#!/usr/bin/env node
'use strict';

// Every place that claims a version must claim the same one. A drifted
// README badge or CHANGELOG heading is not cosmetic here: the self-update
// path compares APP_VERSION against the newest published release tag, so a
// mismatch between what ships and what the docs say sends users chasing a
// version that was never built.

const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const failures = [];

function read(relativePath) {
    return fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
}

function record(label, value) {
    if (!value) {
        failures.push(`${label}: no version found`);
        return null;
    }
    return { label, value };
}

function match(relativePath, pattern, label) {
    const found = read(relativePath).match(pattern);
    return record(label, found && found[1]);
}

const sources = [
    record('package.json', JSON.parse(read('package.json')).version),
    match('astra_downloader/astra_downloader.py', /^APP_VERSION = "([^"]+)"/m,
        'astra_downloader.py APP_VERSION'),
    match('README.md', /img\.shields\.io\/badge\/version-([0-9]+\.[0-9]+\.[0-9]+)-/,
        'README version badge'),
    match('CHANGELOG.md', /^## \[([0-9]+\.[0-9]+\.[0-9]+)\]/m,
        'CHANGELOG newest entry'),
].filter(Boolean);

const versions = new Set(sources.map((source) => source.value));
if (versions.size > 1) {
    failures.push(
        'version sources disagree:\n' +
        sources.map((source) => `  ${source.label} = ${source.value}`).join('\n')
    );
}

for (const source of sources) {
    if (!/^\d+\.\d+\.\d+$/.test(source.value)) {
        failures.push(`${source.label} is not a bare semver triple: ${source.value}`);
    }
}

// The test suite pins APP_VERSION by name so a bump is a deliberate edit.
// If the pin's name and the constant drift apart the pin still passes while
// naming the wrong release, which is exactly the failure this gate exists
// to catch.
const appVersion = sources.find((source) => source.label.includes('APP_VERSION'));
if (appVersion) {
    const pinName = `test_app_version_bumped_to_${appVersion.value.replace(/\./g, '_')}`;
    if (!read('astra_downloader/test_astra_downloader.py').includes(pinName)) {
        failures.push(`the APP_VERSION pin test must be named ${pinName}`);
    }
}

if (failures.length) {
    console.error('[check-versions] FAILED');
    for (const failure of failures) console.error(`  - ${failure}`);
    process.exit(1);
}

console.log(`[check-versions] OK — ${sources.length} sources agree at v${sources[0].value}`);
