'use strict';

// The Scoop package installs the portable one-folder layout, so the app keeps
// its state beside the executable. Scoop persists a single file as a hard link
// and a directory as a junction, and every state file this app writes is
// written by replacing it — `atomic_write_json` and `atomic_copy_verified`
// both `os.replace`, which drops the hard link and leaves the persisted copy
// empty. Listing the files individually therefore looked right and lost the
// data anyway. One persisted directory is the shape that survives, because a
// write inside a junction lands in the persist directory.

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

function constant(name) {
    const match = new RegExp(`^${name} = ['"]([^'"]+)['"]`, 'm').exec(composition);
    assert.ok(match, `the composition root must define ${name}`);
    return match[1];
}

test('the manifest persists the one directory the app keeps state in', () => {
    // Every state path lives under this directory, so the list cannot drift as
    // state files are added — which is what let download-temp, the Whisper
    // model and the rollback copies go missing from the previous list.
    assert.deepEqual(manifest.persist, [constant('PORTABLE_STATE_DIRNAME')]);
});

test('nothing persisted is a file the app replaces atomically', () => {
    // A hard link does not survive os.replace. Anything with an extension here
    // is a file, and every state file this app writes is replaced rather than
    // appended, so a file in this list is a file that will come back empty.
    const offenders = (manifest.persist || []).filter(
        (entry) => path.extname(entry) !== '',
    );
    assert.deepEqual(
        offenders, [],
        'persist a directory instead: a persisted file is hard-linked, and the '
        + 'app replaces its state files rather than writing them in place, '
        + 'which severs the link and leaves the persisted copy empty',
    );
});

test('the portable marker is not persisted', () => {
    // It ships inside the zip and identifies the layout. A persisted copy
    // would survive a switch to a different package shape and keep claiming
    // the old one.
    assert.ok(
        !(manifest.persist || []).includes(constant('PORTABLE_MARKER_NAME')),
        'the portable marker must not be persisted',
    );
});

test('the manifest installs the artifact that carries the portable marker', () => {
    // The persist entry is only correct for the portable layout. If the
    // package ever installs the one-file executable instead, state moves to
    // %LOCALAPPDATA% and the persisted directory is never written.
    assert.match(
        manifest.architecture['64bit'].url, /AstraDownloader-onedir\.zip$/,
        'the persist entry assumes the one-folder artifact',
    );
});

test('a portable launch resolves its state under the persisted directory', () => {
    // The manifest is only half of it: the app has to actually put its state
    // there. This pins the two together, since the persist entry is derived
    // from the same constant the resolver uses.
    assert.match(
        composition,
        /def portable_state_dir\([\s\S]*?return root \/ PORTABLE_STATE_DIRNAME/,
        'portable_state_dir must resolve new installs into the persisted '
        + 'directory named by PORTABLE_STATE_DIRNAME',
    );
});
