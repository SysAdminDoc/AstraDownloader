'use strict';

// The Scoop package installs the portable one-folder layout, so the state root
// is the versioned app directory itself. Scoop links only `persist` entries out
// of that directory, so anything missing from the list is destroyed on
// `scoop update`. The list shipped empty, which meant settings, history, queue,
// subscriptions and stored sign-ins were all discarded by an update.
//
// A hand-kept list drifts the first time someone adds a state file, so the
// expected set is derived from the source that names those paths.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '..');
const manifest = JSON.parse(
    fs.readFileSync(
        path.join(repoRoot, 'packaging', 'scoop', 'astra-downloader.json'), 'utf8',
    ),
);
const composition = fs.readFileSync(
    path.join(repoRoot, 'astra_downloader', 'astra_downloader.py'), 'utf8',
);
const downloadSource = fs.readFileSync(
    path.join(repoRoot, 'astra_downloader', 'download.py'), 'utf8',
);

// Written into the state root but deliberately not persisted, each for a
// reason rather than because nobody got to it.
const NOT_PERSISTED = new Map([
    // Ships inside the package; a persisted copy would shadow the new one.
    ['AstraDownloader.ico', 'ships in the package'],
    // The removed all-download lock. Startup sweeps it; persisting it would
    // carry a file the app exists to delete.
    ['archive.txt', 'legacy file the app sweeps on startup'],
    // The program itself. Persisting it would link the old executable over
    // every future version, so an update would install and then run the
    // binary it just replaced.
    ['AstraDownloader.exe', 'the executable the package ships'],
]);

function statePathsNamedInSource() {
    const names = new Set();
    for (const match of composition.matchAll(/INSTALL_DIR \/ ['"]([^'"]+)['"]/g)) {
        names.add(match[1]);
    }
    const loginDir = /SITE_LOGIN_DIRNAME = ['"]([^'"]+)['"]/.exec(downloadSource);
    assert.ok(loginDir, 'download.py must name the sign-in directory');
    names.add(loginDir[1]);
    return names;
}

test('every state path the app writes is persisted by the Scoop manifest', () => {
    const persisted = new Set(manifest.persist || []);
    assert.ok(persisted.size > 0, 'the manifest must persist the portable state');

    const missing = [];
    for (const name of statePathsNamedInSource()) {
        if (persisted.has(name) || NOT_PERSISTED.has(name)) continue;
        missing.push(name);
    }
    assert.deepEqual(
        missing, [],
        'these paths are written into the Scoop install directory and would be '
        + 'destroyed by `scoop update`. Add them to `persist`, or add them to '
        + 'NOT_PERSISTED here with the reason they should not survive.',
    );
});

test('the manifest persists nothing the app does not actually write', () => {
    const named = statePathsNamedInSource();
    const stray = (manifest.persist || []).filter((entry) => !named.has(entry));
    assert.deepEqual(
        stray, [],
        'persisting a path the app never writes makes Scoop create an empty '
        + 'placeholder for it on install',
    );
});

test('the portable marker is not persisted', () => {
    // It ships inside the zip and identifies the layout. A persisted copy
    // would survive a switch to a different package shape and keep claiming
    // the old one.
    const marker = /PORTABLE_MARKER_NAME = ['"]([^'"]+)['"]/.exec(composition);
    assert.ok(marker, 'the composition root must name the portable marker');
    assert.ok(
        !(manifest.persist || []).includes(marker[1]),
        `${marker[1]} must not be persisted`,
    );
});

test('the manifest installs the artifact that carries the portable marker', () => {
    // The persist list above is only correct for the portable layout. If the
    // package ever installs the one-file executable instead, state moves to
    // %LOCALAPPDATA% and every entry becomes an empty placeholder.
    const url = manifest.architecture['64bit'].url;
    assert.match(
        url, /AstraDownloader-onedir\.zip$/,
        'the persist list assumes the one-folder artifact',
    );
});
