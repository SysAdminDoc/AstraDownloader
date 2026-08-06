#!/usr/bin/env node
'use strict';

// Keep every companion port consumer tied to the checked-in JSON catalogue.
// A port mismatch is a functional failure: the downloader can bind on one
// port while the browser extension probes or is permitted to contact another.
//
// This repository owns the SERVER half of that contract, so it checks the
// generated Python module and the config default. The consumer half — the
// extension manifest's host permissions and CSP, and the userscript's
// fallback list — is checked in the Astra Deck repository against its own
// copy of scripts/companion-port-catalogue.json. Both copies must stay
// byte-identical; changing the ports is a two-repository change.

const fs = require('node:fs');
const path = require('node:path');
const { COMPANION_PORT_CATALOGUE } = require('./companion-port-catalogue');

const ROOT = path.join(__dirname, '..');

function read(relativePath) {
    return fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
}

function fail(message) {
    throw new Error(`[check-companion-port-catalogue] ${message}`);
}

function check(condition, message) {
    if (!condition) fail(message);
}

const python = read('astra_downloader/companion_ports.py');
check(python.includes(`PORT_HOST = "${COMPANION_PORT_CATALOGUE.host}"`),
    'generated Python host does not match the catalogue');
check(python.includes(`COMPANION_ORIGIN = "${COMPANION_PORT_CATALOGUE.origin}"`),
    'generated Python origin does not match the catalogue');
check(python.includes(`PORT_FALLBACKS = [${COMPANION_PORT_CATALOGUE.ports.join(', ')}]`),
    'generated Python fallback ports do not match the catalogue');
check(python.includes('SERVER_PORT = PORT_FALLBACKS[0]'),
    'generated Python primary port must derive from PORT_FALLBACKS');
check(!/^PORT_FALLBACKS\s*=/m.test(read('astra_downloader/astra_downloader.py')),
    'astra_downloader.py must import, not redeclare, PORT_FALLBACKS');
check(read('astra_downloader/config.py').includes('clamp_int(data.get("ServerPort"), SERVER_PORT'),
    'config.py must use the generated primary port as its default');

// The catalogue is a cross-repository contract, so its shape is pinned here
// too: a silently truncated list would still "match" the generated module.
check(Array.isArray(COMPANION_PORT_CATALOGUE.ports) && COMPANION_PORT_CATALOGUE.ports.length >= 2,
    'the catalogue must declare a primary port and at least one fallback');
check(COMPANION_PORT_CATALOGUE.ports.every((port) => Number.isInteger(port) && port > 1024 && port < 65536),
    'every catalogue port must be an unprivileged integer port');
check(new Set(COMPANION_PORT_CATALOGUE.ports).size === COMPANION_PORT_CATALOGUE.ports.length,
    'the catalogue must not repeat a port');
check(COMPANION_PORT_CATALOGUE.host === '127.0.0.1',
    'the companion must stay bound to loopback');

console.log(`[check-companion-port-catalogue] OK — ${COMPANION_PORT_CATALOGUE.ports.length} ports align with the generated Python module`);
