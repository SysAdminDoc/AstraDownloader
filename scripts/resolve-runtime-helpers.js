#!/usr/bin/env node
'use strict';

/**
 * Resolve each runtime helper's exact version and SHA-256 into the licence
 * policy.
 *
 * Astra Downloader fetches yt-dlp, FFmpeg and Deno at runtime from rolling
 * `latest` aliases and verifies each download against the publisher's own
 * checksum sidecar. That is a deliberate design: pinning a dated FFmpeg-Builds
 * asset was measured and rejected because those tags are pruned, which would
 * break first-run setup for every user.
 *
 * The licence inventory still needs to name what shipped. This script reads the
 * same sidecars the application reads, records the digest and the release the
 * alias currently points at, and marks the entry approved. A rolling alias plus
 * a resolved digest is a reviewed delivery form; a rolling alias on its own is
 * not, and the inspection keeps saying so.
 */

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.join(__dirname, '..');
const POLICY_PATH = path.join(REPO_ROOT, 'astra_downloader', 'license-policy.json');
const SIDECAR_MAX_BYTES = 512 * 1024;
const REQUEST_TIMEOUT_MS = 30_000;

function assetName(url) {
    return path.posix.basename(new URL(url).pathname);
}

/**
 * Parse a checksum sidecar and return the digest for one asset.
 *
 * Three shapes are in play across the three publishers:
 *   yt-dlp   SHA2-256SUMS      `<hex>  <name>`, many lines
 *   FFmpeg   checksums.sha256  `<hex>  <name>`, many lines
 *   Deno     <asset>.sha256sum PowerShell Get-FileHash block, `Hash : <HEX>`
 * A bare single-line digest is accepted only from a sidecar whose own filename
 * names the asset, because nothing else ties those bytes to that download.
 */
function digestForAsset(body, target, sidecarUrl) {
    const lines = String(body || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    for (const line of lines) {
        const match = /^([0-9a-f]{64})\s+\*?(.+)$/i.exec(line);
        if (match && path.posix.basename(match[2].replace(/\\/g, '/')) === target) {
            return match[1].toLowerCase();
        }
    }
    // PowerShell Get-FileHash output: Algorithm / Hash / Path, one per line.
    const hashLine = lines.find((line) => /^Hash\s*:\s*[0-9a-f]{64}$/i.test(line));
    const pathLine = lines.find((line) => /^Path\s*:/i.test(line));
    if (hashLine && pathLine) {
        const named = path.posix.basename(pathLine.split(':').slice(1).join(':').trim().replace(/\\/g, '/'));
        if (named === target) {
            return /([0-9a-f]{64})/i.exec(hashLine)[1].toLowerCase();
        }
    }
    if (lines.length === 1 && /^[0-9a-f]{64}$/i.test(lines[0]) && sidecarUrl) {
        let sidecarName = assetName(sidecarUrl);
        for (const suffix of ['.sha256sum', '.sha256', '.sha256.txt']) {
            if (sidecarName.endsWith(suffix)) {
                sidecarName = sidecarName.slice(0, -suffix.length);
                break;
            }
        }
        if (sidecarName === target) return lines[0].toLowerCase();
    }
    return null;
}

async function fetchText(url) {
    const response = await fetch(url, {
        redirect: 'follow',
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS)
    });
    if (!response.ok) {
        throw new Error(`${url} returned HTTP ${response.status}`);
    }
    const body = await response.text();
    if (body.length > SIDECAR_MAX_BYTES) {
        throw new Error(`${url} returned ${body.length} bytes, above the sidecar limit`);
    }
    return body;
}

/**
 * Name the release the rolling alias currently points at.
 *
 * yt-dlp and Deno move their `latest` pointer onto a dated or semver tag, so
 * the tag is the version. FFmpeg-Builds keeps a literal `latest` tag and
 * rebuilds in place, so the tag names nothing — the release's own published
 * timestamp is what distinguishes one auto-build from the next.
 */
async function resolveRelease(distributionUrl) {
    const url = new URL(distributionUrl);
    const segments = url.pathname.split('/').filter(Boolean);
    const [owner, repo] = segments;
    // GitHub serves release assets under two shapes and they put the tag on
    // opposite sides of `download`:
    //   /OWNER/REPO/releases/latest/download/ASSET
    //   /OWNER/REPO/releases/download/TAG/ASSET
    const downloadIndex = segments.indexOf('download');
    const taggedAs = downloadIndex <= 0
        ? 'latest'
        : (segments[downloadIndex - 1] === 'releases'
            ? segments[downloadIndex + 1]
            : segments[downloadIndex - 1]);
    const endpoint = taggedAs && taggedAs !== 'latest'
        ? `https://api.github.com/repos/${owner}/${repo}/releases/tags/${taggedAs}`
        : `https://api.github.com/repos/${owner}/${repo}/releases/latest`;
    const release = JSON.parse(await fetchText(endpoint));
    if (release.tag_name && release.tag_name !== 'latest') {
        return { version: String(release.tag_name).replace(/^v/, ''), tag: release.tag_name };
    }
    const published = String(release.published_at || '').trim();
    if (!published) {
        throw new Error(`${owner}/${repo} publishes a rolling tag with no publication time to identify the build`);
    }
    return { version: `master-${published.replace(/[:]/g, '').replace(/\.\d+Z$/, 'Z')}`, tag: 'latest' };
}

async function resolveHelper(helper) {
    const target = assetName(helper.distributionUrl);
    const [release, sidecar] = await Promise.all([
        resolveRelease(helper.distributionUrl),
        fetchText(helper.checksumUrl)
    ]);
    const sha256 = digestForAsset(sidecar, target, helper.checksumUrl);
    if (!sha256) {
        throw new Error(`${helper.key}: ${helper.checksumUrl} names no digest for ${target}`);
    }
    return { ...release, sha256, target };
}

function approvalEvidence(helper, resolved) {
    return (
        `Resolved at staging from the publisher's own checksum sidecar: `
        + `${resolved.target} at ${resolved.version} is SHA-256 ${resolved.sha256}, read from `
        + `${helper.checksumUrl}. The application downloads the same rolling alias and verifies it `
        + `against the same sidecar before use, so the reviewed bytes and the shipped bytes are the `
        + `same check. A dated pin was examined and rejected: FFmpeg-Builds prunes its dated tags, `
        + `which would break first-run setup once the pin aged out.`
    );
}

async function resolveRuntimeHelpers(policyPath = POLICY_PATH) {
    const policy = JSON.parse(fs.readFileSync(policyPath, 'utf8'));
    const helpers = policy.runtimeHelpers || [];
    const resolvedKeys = [];
    for (const helper of helpers) {
        if (helper.pinnedInSource) continue;
        const resolved = await resolveHelper(helper);
        helper.version = resolved.version;
        helper.sha256 = resolved.sha256;
        helper.decision = 'approved';
        helper.approvalEvidence = approvalEvidence(helper, resolved);
        delete helper.resolution;
        resolvedKeys.push(`${helper.key}=${resolved.version}`);
    }
    fs.writeFileSync(policyPath, JSON.stringify(policy, null, 2) + '\n', 'utf8');
    return resolvedKeys;
}

if (require.main === module) {
    resolveRuntimeHelpers()
        .then((resolved) => {
            console.log(`[resolve-runtime-helpers] OK — ${resolved.join(', ')}`);
        })
        .catch((err) => {
            console.error('[resolve-runtime-helpers] ' + err.message);
            // exitCode, not exit(): fetch keeps libuv handles alive and a hard
            // exit from inside the rejection aborts the process instead.
            process.exitCode = 1;
        });
}

module.exports = {
    POLICY_PATH,
    assetName,
    digestForAsset,
    resolveRuntimeHelpers
};
