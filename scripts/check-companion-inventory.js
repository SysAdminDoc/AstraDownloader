#!/usr/bin/env node
'use strict';

const fs = require('fs');
const crypto = require('crypto');
const path = require('path');
const { buildCompanionInventory, COMPANION_EXE_NAME } = require('./companion-license-inventory');

const REPO_ROOT = path.join(__dirname, '..');
const BUILD_DIR = path.join(REPO_ROOT, 'build');

function sha256(filePath) {
    return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

function main() {
    const exePath = path.join(BUILD_DIR, COMPANION_EXE_NAME);
    const inventory = buildCompanionInventory(REPO_ROOT, BUILD_DIR);
    if (!inventory.components.length || !inventory.dependencies.length) {
        throw new Error('staged companion inventory is empty');
    }
    console.log(
        `Companion inventory: ${inventory.components.length} components; ` +
        `${inventory.dependencies.length} dependency edges; SHA-256 ${sha256(exePath)}`
    );
}

try {
    main();
} catch (error) {
    console.error(`[check-companion-inventory] ${error.message}`);
    process.exitCode = 1;
}
