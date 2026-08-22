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
 * Blocks are paired, not scanned independently, and the application's
 * _parse_get_filehash_block does the same — the evidence written into the
 * policy claims the reviewed bytes and the shipped bytes are the same check,
 * so the two parsers have to agree on identical input.
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
    // Paired per block, matching _parse_get_filehash_block in the application,
    // so a sidecar covering two assets cannot hand one asset's digest to the
    // other. The two parsers have to agree — the evidence this script records
    // claims the reviewed bytes and the shipped bytes are the same check.
    const pairs = [];
    let pending = null;
    for (const line of lines) {
        const hash = /^Hash\s*:\s*([0-9a-f]{64})$/i.exec(line);
        if (hash) {
            pending = hash[1].toLowerCase();
            continue;
        }
        const named = /^Path\s*:\s*(.+)$/i.exec(line);
        if (named && pending) {
            pairs.push([pending, path.posix.basename(named[1].trim().replace(/\\/g, '/'))]);
            pending = null;
        }
    }
    for (const [digest, named] of pairs) {
        if (named === target) return digest;
    }
    if (pairs.length) return null;
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

/**
 * Read the URLs a pinned helper is resolved from.
 *
 * The application can pin a managed binary at runtime, and a release can pin
 * one too. The URLs are named explicitly rather than derived: each publisher
 * arranges a per-release asset path differently, and guessing one produces a
 * 404 at staging or, worse, a digest for the wrong bytes. A `pinnedVersion`
 * without them is refused, so a pin can never quietly fall back to the
 * rolling alias and record a version nobody chose.
 */
function pinnedSources(helper) {
    const version = String(helper.pinnedVersion || '').trim();
    if (!version) return null;
    const distributionUrl = String(helper.pinnedDistributionUrl || '').trim();
    const checksumUrl = String(helper.pinnedChecksumUrl || '').trim();
    if (!distributionUrl || !checksumUrl) {
        throw new Error(
            `${helper.key}: pinnedVersion ${version} needs pinnedDistributionUrl `
            + 'and pinnedChecksumUrl; a pin must not fall back to the rolling alias'
        );
    }
    return { version, distributionUrl, checksumUrl };
}

async function resolveHelper(helper) {
    const pinned = pinnedSources(helper);
    const distributionUrl = pinned ? pinned.distributionUrl : helper.distributionUrl;
    const checksumUrl = pinned ? pinned.checksumUrl : helper.checksumUrl;
    const target = assetName(distributionUrl);
    const [release, sidecar] = await Promise.all([
        pinned
            ? Promise.resolve({ version: pinned.version, tag: pinned.version })
            : resolveRelease(distributionUrl),
        fetchText(checksumUrl)
    ]);
    const sha256 = digestForAsset(sidecar, target, checksumUrl);
    if (!sha256) {
        throw new Error(`${helper.key}: ${checksumUrl} names no digest for ${target}`);
    }
    return { ...release, sha256, target, pinned: Boolean(pinned), checksumUrl };
}

function approvalEvidence(helper, resolved) {
    if (resolved.pinned) {
        return (
            `Pinned rather than resolved from a rolling alias: ${resolved.target} at `
            + `${resolved.version} is SHA-256 ${resolved.sha256}, read from `
            + `${resolved.checksumUrl}, and this entry's distribution URL names that `
            + `release rather than an alias. Note what this does NOT claim: a user can `
            + `pin the same binary at runtime, and that pin is a separate setting this `
            + `inventory neither reads nor constrains. The pin here has to be carried `
            + `forward by hand, which is the cost of naming an exact release — `
            + `FFmpeg-Builds prunes its dated tags, so a pin there ages out of existence.`
        );
    }
    return (
        `Resolved at staging from the publisher's own checksum sidecar: `
        + `${resolved.target} at ${resolved.version} is SHA-256 ${resolved.sha256}, read from `
        + `${resolved.checksumUrl}. The application downloads the same rolling alias and verifies it `
        + `against the same sidecar before use, so the reviewed bytes and the shipped bytes are the `
        + `same check. A dated pin was examined and rejected: FFmpeg-Builds prunes its dated tags, `
        + `which would break first-run setup once the pin aged out.`
    );
}

async function resolveRuntimeHelpers(policyPath = POLICY_PATH) {
    const policy = JSON.parse(fs.readFileSync(policyPath, 'utf8'));
    const helpers = policy.runtimeHelpers || [];
    const resolvedKeys = [];
    const skipped = [];
    for (const helper of helpers) {
        if (helper.pinnedInSource) continue;
        // Resolving a digest is not a licence review. `licenseReviewed` is the
        // human mark, set by hand once someone has read the helper's terms;
        // without it this script leaves the entry alone and the inventory gate
        // keeps refusing the release. Otherwise adding a runtime helper to the
        // policy would approve it by simply running staging.
        if (helper.licenseReviewed !== true) {
            skipped.push(helper.key);
            continue;
        }
        const resolved = await resolveHelper(helper);
        helper.version = resolved.version;
        helper.sha256 = resolved.sha256;
        helper.decision = 'approved';
        if (resolved.pinned) {
            // The digest came from the pinned release, so the entry has to
            // name that release too. A pinned digest sitting beside a
            // `.../releases/latest/download/...` URL reads as a resolved
            // alias, and the inspection waves it through because a digest
            // is present.
            helper.distributionUrl = helper.pinnedDistributionUrl;
            helper.checksumUrl = helper.pinnedChecksumUrl;
        }
        helper.approvalEvidence = approvalEvidence(helper, resolved);
        // The corresponding-source link has to name the version this entry
        // records; the digest does not cover it and the inspection says so.
        if (resolved.tag && resolved.tag !== 'latest' && helper.sourceUrl) {
            helper.sourceUrl = helper.sourceUrl
                .replace('/releases/latest/download/', `/releases/download/${resolved.tag}/`)
                .replace('/releases/download/latest/', `/releases/download/${resolved.tag}/`);
        }
        delete helper.resolution;
        resolvedKeys.push(`${helper.key}=${resolved.version}`);
    }
    if (skipped.length) {
        throw new Error(
            `runtime helper(s) awaiting a human licence review: ${skipped.join(', ')}. `
            + 'Read the terms, then set "licenseReviewed": true on the policy entry.'
        );
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
    pinnedSources,
    approvalEvidence,
    resolveRuntimeHelpers
};
