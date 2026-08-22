#!/usr/bin/env node
'use strict';

// Every place that claims a version must claim the same one. A drifted
// README badge or CHANGELOG heading is not cosmetic here: the self-update
// path compares APP_VERSION against the newest published release tag, so a
// mismatch between what ships and what the docs say sends users chasing a
// version that was never built.

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const { wingetDigestFailures } = require('./stage-companion-release');

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

function checkWingetManifest(version) {
    const manifestRoot = path.join(
        ROOT, 'packaging', 'winget', 'manifests', 's', 'SysAdminDoc', 'AstraDownloader'
    );
    let versionDirectories;
    try {
        versionDirectories = fs.readdirSync(manifestRoot, { withFileTypes: true })
            .filter((entry) => entry.isDirectory() && /^\d+\.\d+\.\d+$/.test(entry.name))
            .map((entry) => entry.name)
            .sort();
    } catch (error) {
        failures.push(`winget manifest: could not read ${manifestRoot}: ${error.message}`);
        return null;
    }
    if (versionDirectories.length !== 1 || versionDirectories[0] !== version) {
        failures.push(
            `winget manifest directories must contain only ${version}; found ` +
            (versionDirectories.join(', ') || 'none')
        );
        return null;
    }

    const directory = path.join(manifestRoot, version);
    const files = fs.readdirSync(directory)
        .filter((name) => name.endsWith('.yaml'))
        .sort();
    if (files.length !== 3) {
        failures.push(`winget manifest ${version}: expected three YAML files, found ${files.length}`);
    }
    const contents = files.map((name) => ({ name, text: fs.readFileSync(path.join(directory, name), 'utf8') }));
    for (const { name, text } of contents) {
        const packageVersion = text.match(/^PackageVersion:\s*([^\s#]+)/m);
        if (!packageVersion || packageVersion[1] !== version) {
            failures.push(`winget ${name}: PackageVersion must be ${version}`);
        }
    }

    const installer = contents.find(({ name }) => name.endsWith('.installer.yaml'));
    if (!installer) {
        failures.push(`winget manifest ${version}: installer manifest is missing`);
    } else {
        const expectedUrl = `https://github.com/SysAdminDoc/AstraDownloader/releases/download/v${version}/AstraDownloader.exe`;
        const installerUrl = installer.text.match(/^\s+InstallerUrl:\s*(\S+)/m);
        const checksum = installer.text.match(/^\s+InstallerSha256:\s*([0-9a-f]{64})\s*$/im);
        if (!installerUrl || installerUrl[1] !== expectedUrl) {
            failures.push(`winget ${installer.name}: InstallerUrl must target v${version}`);
        }
        if (!checksum) {
            failures.push(`winget ${installer.name}: InstallerSha256 must be a 64-digit hex digest`);
        } else {
            // A well-formed digest is not a correct one: 2.7.0 shipped a
            // manifest digest that matched no artifact in existence. Compare
            // against the staged build whenever one exists for this version.
            let stagedMetadata = null;
            try {
                stagedMetadata = JSON.parse(read('build/companion-build-metadata.json'));
            } catch (error) {
                stagedMetadata = null;
            }
            failures.push(...wingetDigestFailures(installer.text, version, stagedMetadata));
        }
    }

    const locale = contents.find(({ name }) => name.endsWith('.locale.en-US.yaml'));
    if (locale) {
        const releaseNotesUrl = locale.text.match(/^ReleaseNotesUrl:\s*(\S+)/m);
        const expectedReleaseNotes = `https://github.com/SysAdminDoc/AstraDownloader/releases/tag/v${version}`;
        if (!releaseNotesUrl || releaseNotesUrl[1] !== expectedReleaseNotes) {
            failures.push(`winget ${locale.name}: ReleaseNotesUrl must target v${version}`);
        }
    }
    return record('winget manifest PackageVersion', version);
}

function checkScoopManifest(version) {
    // Same failure the winget manifest had at 2.7.0: a manifest that names a
    // version nobody published, or a hash that matches no artifact, installs
    // nothing and says nothing. Both are read from the staged sidecar.
    const relativePath = path.posix.join('packaging', 'scoop', 'astra-downloader.json');
    let manifest;
    try {
        manifest = JSON.parse(read(relativePath));
    } catch (error) {
        failures.push(`scoop manifest: could not read ${relativePath}: ${error.message}`);
        return null;
    }

    const archive = 'AstraDownloader-onedir.zip';
    const expectedUrl =
        `https://github.com/SysAdminDoc/AstraDownloader/releases/download/v${version}/${archive}`;
    const arch = (manifest.architecture || {})['64bit'] || {};
    if (arch.url !== expectedUrl) {
        failures.push(`scoop manifest: 64bit url must be ${expectedUrl}`);
    }
    if (!/^[0-9a-f]{64}$/i.test(String(arch.hash || ''))) {
        failures.push('scoop manifest: 64bit hash must be a SHA-256 digest');
    } else {
        let sidecar = null;
        for (const candidate of [`build/${archive}.sha256`, `${archive}.sha256`]) {
            try {
                sidecar = read(candidate);
                break;
            } catch (error) {
                sidecar = null;
            }
        }
        const staged = sidecar && /^([0-9a-f]{64})/i.exec(sidecar.trim());
        if (staged && staged[1].toLowerCase() !== String(arch.hash).toLowerCase()) {
            failures.push(
                `scoop manifest: hash ${arch.hash} does not match the staged ${archive} `
                + `(${staged[1]})`
            );
        }
    }
    if (manifest.license !== 'MIT') {
        failures.push('scoop manifest: license must match the repository LICENSE');
    }
    if (manifest.bin !== 'AstraDownloader.exe') {
        failures.push('scoop manifest: bin must be AstraDownloader.exe');
    }
    if (!manifest.autoupdate || !manifest.checkver) {
        failures.push('scoop manifest: checkver and autoupdate are required by Extras');
    }
    return record('scoop manifest version', manifest.version);
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

const appVersionForManifests = sources.find(
    (source) => source.label.includes('APP_VERSION')
);
if (appVersionForManifests) {
    const scoop = checkScoopManifest(appVersionForManifests.value);
    if (scoop) sources.push(scoop);
}

const appVersion = sources.find((source) => source.label.includes('APP_VERSION'));
if (appVersion) {
    const winget = checkWingetManifest(appVersion.value);
    if (winget) sources.push(winget);
}

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
if (appVersion) {
    const pinName = `test_app_version_bumped_to_${appVersion.value.replace(/\./g, '_')}`;
    // Across every test module rather than one named file: the suite is split
    // by domain now, and naming a single file made this gate depend on which
    // module the pin happens to live in.
    const testModules = fs.readdirSync(path.join(ROOT, 'astra_downloader'))
        .filter((name) => /^test_.*\.py$/.test(name));
    const pinned = testModules.some(
        (name) => read(path.posix.join('astra_downloader', name)).includes(pinName)
    );
    if (!pinned) {
        failures.push(`the APP_VERSION pin test must be named ${pinName}`);
    }
}

// Agreeing with itself is not the same as having shipped. Six versions were
// cut with every version source in agreement and no tag or release behind any
// of them, so the updater's `releases/latest` feed and the extension's
// installer link both resolved to a build from six versions earlier. The tag
// is checked rather than the release because this must work offline and
// because a tag is the thing a release is cut from.
if (appVersion) {
    const tag = `v${appVersion.value}`;
    const listed = spawnSync('git', ['tag', '--list', tag], { cwd: ROOT, encoding: 'utf8' });
    if (listed.error || listed.status !== 0) {
        failures.push(`could not list git tags to confirm ${tag} exists`);
    } else if (listed.stdout.trim() !== tag) {
        failures.push(
            `APP_VERSION is ${appVersion.value} but no ${tag} tag exists — ` +
            'the self-update feed and the extension installer link both resolve to the newest ' +
            'published release, so an untagged version has not shipped to anyone'
        );
    }
}

if (failures.length) {
    console.error('[check-versions] FAILED');
    for (const failure of failures) console.error(`  - ${failure}`);
    process.exit(1);
}

console.log(`[check-versions] OK — ${sources.length} sources agree at v${sources[0].value}`);
