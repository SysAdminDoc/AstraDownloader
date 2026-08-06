#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { COMPANION_PORT_CATALOGUE } = require('./companion-port-catalogue');

// This repository generates only the server-side module. The matching
// extension-side JavaScript module is generated in the Astra Deck repository
// from its own copy of companion-port-catalogue.json — the two copies of the
// JSON are the contract, and changing the ports is a two-repository change.
const ROOT = path.join(__dirname, '..');
const PYTHON_PATH = path.join(ROOT, 'astra_downloader', 'companion_ports.py');

function renderPython(catalogue) {
    return `"""Generated companion port catalogue. Do not edit; regenerate from scripts/companion-port-catalogue.json."""\n\nPORT_HOST = ${JSON.stringify(catalogue.host)}\nCOMPANION_ORIGIN = ${JSON.stringify(catalogue.origin)}\nPORT_FALLBACKS = [${catalogue.ports.join(', ')}]\nSERVER_PORT = PORT_FALLBACKS[0]\nHOST_PERMISSIONS = [${catalogue.hostPermissions.map((value) => JSON.stringify(value)).join(', ')}]\nCSP_ORIGINS = [${catalogue.cspOrigins.map((value) => JSON.stringify(value)).join(', ')}]\n`;
}

fs.writeFileSync(PYTHON_PATH, renderPython(COMPANION_PORT_CATALOGUE), 'utf8');
console.log(`[companion-port-catalogue] generated ${path.relative(ROOT, PYTHON_PATH)}`);
