'use strict';

const test = require('node:test');
const assert = require('node:assert');

const {
    LOCK_NAME,
    RESOLVE_COOLDOWN,
    SBOM_NAME,
    buildCycloneDx,
    renderPylock,
    sbomDescribesArtifact,
    uuidFromDigest,
} = require('../scripts/write-release-provenance');
const { PROPERTY } = require('../scripts/companion-license-inventory');

const ARTIFACT_SHA = 'a'.repeat(64);
const OTHER_SHA = 'b'.repeat(64);

function inventory(artifactSha256) {
    return {
        components: [{
            type: 'library',
            name: 'flask',
            version: '3.1.3',
            licenses: [{ license: { id: 'BSD-3-Clause' } }],
            properties: [
                { name: PROPERTY.artifactSha256, value: artifactSha256 },
            ],
        }],
        dependencies: [{ ref: 'pkg:pypi/flask@3.1.3', dependsOn: [] }],
    };
}

test('the SBOM carries the CISA 2026 minimum elements', () => {
    const sbom = buildCycloneDx(inventory(ARTIFACT_SHA), { name: 'AstraDownloader.exe', sha256: ARTIFACT_SHA }, '2026-08-11T00:00:00.000Z');

    assert.equal(sbom.bomFormat, 'CycloneDX');
    assert.equal(sbom.specVersion, '1.6');
    // Unique identifier, timestamp, author, supplier, tool name.
    assert.match(sbom.serialNumber, /^urn:uuid:[0-9a-f-]{36}$/);
    assert.equal(sbom.metadata.timestamp, '2026-08-11T00:00:00.000Z');
    assert.ok(sbom.metadata.authors.length);
    assert.ok(sbom.metadata.supplier.name);
    assert.equal(sbom.metadata.tools.components[0].name, 'write-release-provenance');
    // Component hash and licence.
    assert.equal(sbom.metadata.component.hashes[0].alg, 'SHA-256');
    assert.equal(sbom.metadata.component.hashes[0].content, ARTIFACT_SHA);
    assert.ok(sbom.metadata.component.licenses.length);
    // Dependency relationships and generation context.
    assert.ok(sbom.dependencies.length);
    const properties = sbom.metadata.properties.map((property) => property.name);
    assert.ok(properties.includes('astra:release:generationContext'));
    assert.ok(properties.includes('astra:release:resolveCooldown'));
});

test('the serial number is derived from the artifact, not random', () => {
    const first = buildCycloneDx(inventory(ARTIFACT_SHA), { name: 'x', sha256: ARTIFACT_SHA }, '2026-08-11T00:00:00.000Z');
    const second = buildCycloneDx(inventory(ARTIFACT_SHA), { name: 'x', sha256: ARTIFACT_SHA }, '2026-08-11T01:00:00.000Z');
    assert.equal(first.serialNumber, second.serialNumber);

    const other = buildCycloneDx(inventory(OTHER_SHA), { name: 'x', sha256: OTHER_SHA }, '2026-08-11T00:00:00.000Z');
    assert.notEqual(first.serialNumber, other.serialNumber);
    assert.match(uuidFromDigest(ARTIFACT_SHA), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$/);
});

test('a stale SBOM is refused rather than shipped beside a fresh binary', () => {
    const sbom = buildCycloneDx(inventory(ARTIFACT_SHA), { name: 'x', sha256: ARTIFACT_SHA }, '2026-08-11T00:00:00.000Z');
    assert.equal(sbomDescribesArtifact(sbom, ARTIFACT_SHA), true);

    // The binary was rebuilt; the SBOM was not regenerated.
    assert.equal(sbomDescribesArtifact(sbom, OTHER_SHA), false);

    // The envelope matches but a component still names the previous build.
    const mixed = buildCycloneDx(inventory(OTHER_SHA), { name: 'x', sha256: ARTIFACT_SHA }, '2026-08-11T00:00:00.000Z');
    assert.equal(
        sbomDescribesArtifact(mixed, ARTIFACT_SHA), false,
        'a component stamped with another build must not pass the artifact check'
    );
});

test('the lock file is PEP 751 shaped and carries a hash for every artifact', () => {
    const rendered = renderPylock([{
        name: 'flask',
        version: '3.1.3',
        wheels: [{ name: 'flask-3.1.3-py3-none-any.whl', url: 'https://files.pythonhosted.org/flask.whl', sha256: 'c'.repeat(64) }],
        sdist: { name: 'flask-3.1.3.tar.gz', url: 'https://files.pythonhosted.org/flask.tar.gz', sha256: 'd'.repeat(64) },
    }], '2026-08-11T00:00:00.000Z');

    assert.match(rendered, /^lock-version = "1\.0"$/m);
    assert.match(rendered, /^requires-python = ">=3\.11"$/m);
    assert.match(rendered, /^\[\[packages\]\]$/m);
    assert.match(rendered, /^name = "flask"$/m);
    assert.match(rendered, /^\[\[packages\.wheels\]\]$/m);
    assert.match(rendered, /hashes = \{ sha256 = "c{64}" \}/);
    assert.match(rendered, /^\[packages\.sdist\]$/m);
    assert.ok(rendered.includes(RESOLVE_COOLDOWN), 'the resolve cooldown must be recorded in the lock');
});

test('the published artifact names are stable', () => {
    // stage-companion-release.js refuses to stage without these exact files.
    assert.equal(SBOM_NAME, 'astra-downloader-sbom.cdx.json');
    assert.equal(LOCK_NAME, 'pylock.toml');
});
